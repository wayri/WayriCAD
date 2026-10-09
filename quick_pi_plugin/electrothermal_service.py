"""Saved-board preparation and source-bound electrothermal study execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def prepare_saved_study(path, study):
    """Extract both geometries from one saved board; never import a sibling plugin."""
    import pcbnew
    from . import board_geometry
    from .service import execute, sink_requests
    from wayricad_runtime.thermal_geometry import collect_thermal_geometry

    electrical = copy.deepcopy(study.get('electrical'))
    if not isinstance(electrical, dict):
        raise ValueError('Steady saved-board coupling requires electrical net/source/sink settings.')
    if electrical.get('model_dimension','2.5d')!='2.5d' or electrical.get('load_resistance_ohm') is not None or electrical.get('sweep'):
        raise ValueError('Saved-board coupling requires 2.5D prescribed-current loads; 3D, voltage-driven loads and sweeps are separate models.')
    electrical.update(board_path=str(path), action='mesh')
    bundle = execute(electrical)
    mesh, geometry = bundle['mesh'], bundle['geometry']
    board = pcbnew.LoadBoard(str(path))
    thermal = collect_thermal_geometry(board, path, geometry_helpers=board_geometry)

    def terminal(value):
        matches = [t for t in geometry['terminals'] if value in (t['id'], t['label'])]
        if len(matches) != 1:
            raise ValueError('Choose one unambiguous saved pad: ' + str(value))
        row = matches[0]
        return row, mesh['terminal_nodes'][row['id']]

    sinks = []
    for spec in sink_requests(electrical):
        row, nodes = terminal(spec['terminal'])
        sinks.append({**spec, 'nodes': nodes, 'id': row['id'], 'label': row['label']})
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if geometry.get('source_sha256') != sha or thermal.get('source_sha256') != sha:
        raise ValueError('Saved PCB changed between electrical and thermal extraction. Reload and retry.')
    stackup_sha = _digest([{k: layer[k] for k in ('id', 'z_mm', 'thickness_mm')}
                           for layer in thermal['layers']])
    mesh.update(source_sha256=sha, stackup_sha256=stackup_sha)
    thermal['stackup_sha256'] = stackup_sha
    via_maps = {str(via['id']): {k: via[k] for k in ('x_mm', 'y_mm', 'top_layer', 'bottom_layer')}
                | {'policy': 'uniform_axial'} for via in mesh.get('vias', [])}
    # Component loss maps remain explicitly supplied. Physical footprint contacts
    # are available without treating delivered electrical load power as board heat.
    view_components = []
    for fp in board.GetFootprints():
        bounds = fp.GetBoundingBox(False)
        pos = fp.GetPosition()
        view_components.append({'id': fp.m_Uuid.AsString(), 'reference': fp.GetReference(),
            'position_mm': [pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)],
            'bbox_mm': [pcbnew.ToMM(bounds.GetX()), pcbnew.ToMM(bounds.GetY()),
                        pcbnew.ToMM(bounds.GetX()+bounds.GetWidth()),
                        pcbnew.ToMM(bounds.GetY()+bounds.GetHeight())],
            'side': 'bottom' if fp.IsFlipped() else 'top'})
    prepared = {k: copy.deepcopy(v) for k, v in study.items() if k != 'electrical'}
    prepared.update(schema_version=1, mesh=mesh, source_nodes=terminal(electrical['source_terminal'])[1],
        sinks=sinks, source_voltage_V=electrical.get('source_voltage', 1.),
        source_current_limit_A=electrical.get('source_current_limit'),
        electrical_options=electrical.get('options', {}), thermal_geometry=thermal,
        thermal_view={'components': view_components}, via_heat_mappings=via_maps,
        source_sha256=sha, stackup_sha256=stackup_sha)
    return prepared


def execute(request):
    study = request.get('study')
    if not isinstance(study, dict):
        raise ValueError('Electrothermal study must be an object.')
    mode = request.get('mode', 'steady')
    if mode not in ('steady', 'transient'):
        raise ValueError('Choose steady or transient electrothermal mode.')
    source = Path(request['board_path']).resolve() if request.get('board_path') else None
    before = None
    if source:
        if source.suffix.lower() != '.kicad_pcb' or not source.is_file():
            raise ValueError('Choose a saved KiCad PCB.')
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        if request.get('source_sha256') and request['source_sha256'] != before:
            raise ValueError('Saved PCB changed. Reload before running electrothermal coupling.')
    if mode == 'steady':
        from .electrothermal import solve_electrothermal
        if 'electrical' in study:
            if not source:
                raise ValueError('Saved-board electrical selections require a PCB path.')
            resolved = prepare_saved_study(source, study)
        else:
            resolved = copy.deepcopy(study)
        if source:
            for bound in (resolved, resolved.get('mesh', {}), resolved.get('thermal_geometry', {})):
                if bound.get('source_sha256') not in (None, before):
                    raise ValueError('Prepared electrothermal model belongs to a different saved PCB.')
        result = solve_electrothermal(resolved)
    else:
        from .electrothermal_transient import solve_electrothermal_transient
        resolved = copy.deepcopy(study)
        result = solve_electrothermal_transient(resolved)
    if source and hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise ValueError('Saved PCB changed during coupling. Discard this result and reload.')
    study_path = request.get('study_input_path')
    study_sha = request.get('study_file_sha256')
    if study_path and study_sha and hashlib.sha256(Path(study_path).read_bytes()).hexdigest() != study_sha:
        raise ValueError('Input study changed during coupling. Discard the result and reload.')
    return {'electrothermal': result, 'mode': mode, 'study': copy.deepcopy(study),
            'study_sha256': _digest(study), 'source_sha256': before,
            'geometry_origin': 'saved_board' if mode == 'steady' and 'electrical' in study else 'explicit_model',
            'board_binding': ('extracted_geometry' if mode == 'steady' and 'electrical' in study else
                              'provenance_only') if source else None,
            'thermal_outline': resolved.get('thermal_geometry', {}).get('outline', []),
            'board_path': str(source) if source else None,
            'study_input_path': study_path, 'study_file_sha256': study_sha}
