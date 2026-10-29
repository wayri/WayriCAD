"""Small, deterministic view of the solved three-dimensional copper field.

The complete tetrahedral field remains in the JSON result. Display sampling is
only a rendering limit; it does not change numerical results or peak metrics.
"""

import numpy as np


QUANTITIES = {
    'Current density (A/mm²)': 'current_density',
    'Voltage (V)': 'voltage',
    'Loss density (W/mm³)': 'loss_density',
}


def layer_names(bundle):
    """Return copper layers with geometry, plus the interlayer barrel span."""
    layers = [row['name'] for row in bundle['geometry']['layers'] if row.get('polygons')]
    return ['All copper', *layers, 'Interlayer barrels']


def sampled_cells(bundle, layer='All copper', quantity='current_density', limit=5000):
    """Select finite connected cells for a plot without modifying solver data.

    Each planar cell belongs to a saved copper slab by its centroid Z. Cells in
    interlayer barrels appear under Via barrels. A deterministic uniform sample
    limits Matplotlib work on large tetrahedral meshes.
    """
    if quantity not in QUANTITIES.values():
        raise ValueError('Unknown 3D field quantity.')
    if not isinstance(limit, int) or limit < 1:
        raise ValueError('Display cell limit must be positive.')
    result = bundle['result']
    mesh = bundle['mesh']
    centers = np.asarray(result['cell_centroid_mm'], dtype=float)
    if centers.ndim != 2 or centers.shape[1] != 3:
        raise ValueError('3D result has no cell coordinates.')
    layers = [row for row in bundle['geometry']['layers'] if row.get('polygons')]
    belonging = np.full(len(centers), -1, dtype=int)
    for index, row in enumerate(layers):
        middle = float(row['z_mm'])
        half = float(row['thickness_mm']) / 2
        mask = np.abs(centers[:, 2] - middle) <= half + 1e-7
        belonging[mask] = index
    if layer == 'All copper':
        selected = np.ones(len(centers), dtype=bool)
    elif layer == 'Interlayer barrels':
        selected = belonging == -1
    else:
        names = [row['name'] for row in layers]
        if layer not in names:
            raise ValueError('Unknown copper layer.')
        selected = belonging == names.index(layer)
    if quantity == 'current_density':
        vectors = np.asarray([row if row is not None else (np.nan,np.nan,np.nan)
                              for row in result['cell_J_A_mm2']], dtype=float)
        if vectors.shape != centers.shape:
            raise ValueError('3D current-density vectors and cell coordinates disagree.')
        values = np.linalg.norm(vectors, axis=1)
    elif quantity == 'loss_density':
        power = result['cell_power_W']
        volume = result['cell_volume_mm3']
        power = np.asarray(power,dtype=float)
        volume = np.asarray(volume,dtype=float)
        if power.shape != volume.shape:
            raise ValueError('3D cell power and volume counts disagree.')
        values = np.full(power.shape,np.nan)
        np.divide(power,volume,out=values,where=np.isfinite(power)&(volume>0))
    else:
        potentials = np.asarray([np.nan if v is None else v
                                 for v in result['potential_V']], dtype=float)
        tetrahedra = np.asarray(mesh['tetrahedra'], dtype=int)
        values = np.mean(potentials[tetrahedra], axis=1)
    if len(values) != len(centers):
        raise ValueError('3D field and mesh cell counts disagree.')
    selected &= np.isfinite(values) & np.isfinite(centers).all(axis=1)
    indices = np.flatnonzero(selected)
    count = len(indices)
    if count > limit:
        indices = indices[np.linspace(0, count - 1, limit, dtype=int)]
    return centers[indices], values[indices], count


def write_volume_report(path,bundle,*,pocket_kivi=False):
    """Export offline orbit/pan/zoom views and exact sampled cell probes."""
    import json
    from pathlib import Path
    from wayricad_runtime.interactive_plots import interactive_plot
    pocket=None
    if pocket_kivi:
        from .report import _pocket_evidence
        from wayricad_runtime.report_ui import publish_report,report_paths
        pocket=_pocket_evidence(bundle)
        path,_=report_paths(path)
    else:
        path=Path(path).with_suffix('.html');path.parent.mkdir(parents=True,exist_ok=True)
        path.with_suffix('.json').write_text(json.dumps(bundle,allow_nan=False),encoding='utf-8')
    html='<html lang="en"><meta charset="utf-8"><title>Quick PI 3D copper</title><style>body{font:15px system-ui;max-width:1100px;margin:30px auto}figure{margin:18px 0}</style><h1>Quick PI 3D copper</h1><p>Display samples only. Exact complete tetrahedron results are retained in the paired JSON. This is fixed-temperature DC conduction, not AC impedance or thermal transient analysis.</p>'
    from .sankey import sankey_section
    html+=sankey_section(bundle)
    for label,quantity in QUANTITIES.items():
        xyz,values,count=sampled_cells(bundle,quantity=quantity)
        rows=[[float(p[0]),float(p[1]),float(v),'Sampled cell',float(p[2])] for p,v in zip(xyz,values)]
        html+=interactive_plot(label,rows,label,three_d=True)
    if pocket is not None:return publish_report(path,html+'</html>',bundle,pocket_kivi=pocket)
    path.write_text(html+'</html>',encoding='utf-8')
    return {'html':str(path),'json':str(path.with_suffix('.json'))}
