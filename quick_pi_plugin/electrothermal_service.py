"""Saved-board preparation and source-bound electrothermal study execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()



def validate_feedback_inputs(study):
    """Require reviewed physical inputs for the one-click feedback workflow."""
    import math
    settings=study.get('thermal_settings',{});coupling=study.get('coupling',{})
    for key,low,high in [('ambient_c',-273.15,None),('dielectric_k_w_mk',1e-12,None),
                         ('copper_k_w_mk',1e-12,None),('via_plating_mm',1e-12,None),
                         ('board_h_w_m2k',0,None),('board_emissivity',0,1)]:
        value=settings.get(key)
        if (not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value)
                or value<low or high is not None and value>high):
            raise ValueError('Enter an explicit finite thermal_settings.'+key+' in its physical range.')
    bounds=coupling.get('material_temperature_range_c')
    if (not isinstance(bounds,list) or len(bounds)!=2 or
            any(not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) for value in bounds)
            or bounds[0]<-273.15 or bounds[1]<=bounds[0]):
        raise ValueError('Enter a reviewed coupling.material_temperature_range_c [minimum, maximum].')
    cap=coupling.get('temperature_cap_c')
    if not isinstance(cap,(int,float)) or isinstance(cap,bool) or not math.isfinite(cap) or not settings['ambient_c']<=cap<=bounds[1]:
        raise ValueError('Enter an explicit coupling.temperature_cap_c within the material range and at or above ambient.')
    options=study.get('electrical',{}).get('options',{})
    for key in ('resistivity_ohm_m','temperature_coefficient'):
        value=options.get(key)
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0 or key=='resistivity_ohm_m' and value==0:
            raise ValueError('Enter an explicit electrical.options.'+key+'; resistivity is at 20 C.')

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
    if electrical.get('package_conduction'):
        raise ValueError('Explicit package contacts are unsupported in electrothermal coupling.')
    if electrical.get('series'):
        raise ValueError('Saved-board coupling supports one net; series branches require an explicit prepared heat-contact model.')
    specs=sink_requests(electrical)
    if electrical.get('load_power_W') is not None or any('power_W' in spec for spec in specs):
        raise ValueError('Saved-board Joule feedback requires prescribed-current loads; constant-power coupling is unsupported.')
    electrical.update(board_path=str(path), action='mesh')
    # Electrical extraction already owns this exact saved native board. Reuse
    # it for thermal extraction rather than parsing a dense board twice.
    boards = {}
    bundle = execute(electrical,_boards=boards)
    mesh, geometry = bundle['mesh'], bundle['geometry']
    board = next(iter(boards.values())) if boards else pcbnew.LoadBoard(str(path))
    thermal = collect_thermal_geometry(board, path, geometry_helpers=board_geometry)

    from .terminals import resolve_units
    _, source_nodes, sinks, terminal_units = resolve_units(
        electrical, geometry, mesh, specs)
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
    prepared.update(schema_version=1, mesh=mesh, source_nodes=source_nodes,
        sinks=sinks, source_voltage_V=electrical.get('source_voltage', 1.),
        source_current_limit_A=electrical.get('source_current_limit'),
        electrical_options=electrical.get('options', {}), thermal_geometry=thermal,
        thermal_view={'components': view_components}, via_heat_mappings=via_maps,
        source_sha256=sha, stackup_sha256=stackup_sha)
    prepared['terminal_units']=terminal_units
    return prepared


def execute(request):
    study = request.get('study')
    if not isinstance(study, dict):
        raise ValueError('Electrothermal study must be an object.')
    if any(value.get('package_conduction') or value.get('package_contacts') for value in
           (request,study,study.get('mesh',{}),study.get('electrical',{}))):
        raise ValueError('Explicit package contacts are unsupported in electrothermal coupling.')
    if request.get('require_explicit_thermal'):
        validate_feedback_inputs(study)
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
