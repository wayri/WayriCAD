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
        vectors = result['cell_J_A_mm2']
        values = np.asarray([np.linalg.norm(row) if row is not None else np.nan
                             for row in vectors], dtype=float)
    elif quantity == 'loss_density':
        power = result['cell_power_W']
        volume = result['cell_volume_mm3']
        values = np.asarray([float(p) / float(v) if p is not None and v > 0 else np.nan
                             for p, v in zip(power, volume)], dtype=float)
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
