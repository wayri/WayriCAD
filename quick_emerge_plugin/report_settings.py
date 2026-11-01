"""Human-readable active setup evidence; canonical stored configuration is untouched."""
from .advanced import ADVANCED_DEFAULTS, ADVANCED_FIELDS


def active_settings(result):
    """Return scalar category/label/value rows for the physics actually selected.

    Saved-PCB dimensions come from the recorded region, never template defaults.
    Optimization geometry uses the best recorded configuration, while requested
    optimization bounds remain identified separately.
    """
    requested = result['config']
    c = result.get('optimization', {}).get('best_config', requested)
    a = {**ADVANCED_DEFAULTS, **c.get('advanced', {})}
    study = requested.get('advanced', {}).get('study', 'driven')
    mode = c['mode']
    rows = [('Study', 'Study type', study.replace('_', ' '))]

    def add(group, label, value, unit=''):
        rows.append((group, label + (' ['+unit+']' if unit else ''), value))

    def base(group, key, label, unit=''):
        add(group, label, c.get(key), unit)

    thermal = study == 'thermal'
    substrate = study not in ('scattering', 'waveguide')
    if substrate:
        if mode == 'pcb_region':
            recorded = result.get('region', {}).get('substrate', {})
            points = [p for shape in recorded.get('outline', []) for p in shape['outer_mm']]
            for axis, index in (('X', 0), ('Y', 1)):
                span = max(p[index] for p in points)-min(p[index] for p in points) if points else None
                add('Geometry', 'Recorded region extent '+axis, span, 'mm')
            add('Geometry', 'Recorded dielectric separation', recorded.get('thickness_mm'), 'mm')
            if recorded.get('board_thickness_mm') is not None:
                add('Geometry', 'Recorded overall board thickness', recorded['board_thickness_mm'], 'mm')
            for key, label in (('rule_area_id', 'Rule area'), ('signal_net', 'Signal net'), ('reference_net', 'Reference net')):
                base('Geometry', key, label)
        else:
            for key, label in (('substrate_x_mm', 'Substrate extent X'), ('substrate_y_mm', 'Substrate extent Y'), ('thickness_mm', 'Substrate thickness')):
                base('Geometry', key, label, 'mm')
        if not thermal:
            base('Material', 'er', 'Relative permittivity at start frequency')
        if not thermal and mode != 'pcb_region':
            keys = (('patch_width_mm', 'Patch width'), ('patch_length_mm', 'Patch length')) if mode == 'patch' else (('line_length_mm', 'Line length'), ('line_width_mm', 'Line width'))
            if mode == 'patch' and study != 'periodic':
                keys += (('feed_width_mm', 'Feed width'), ('inset_width_mm', 'Inset width'), ('inset_length_mm', 'Inset length'))
            for key, label in keys:
                base('Geometry', key, label, 'mm')
    if not thermal:
        for key, label, unit in (('f_start_hz', 'Sweep start', 'Hz'), ('f_stop_hz', 'Sweep stop', 'Hz'), ('points', 'Requested frequency samples', ''), ('sweep', 'Sweep method', ''), ('resolution', 'Wavelength mesh resolution', '')):
            base('Solve', key, label, unit)
        if study != 'waveguide':
            base('Boundary', 'air_margin_mm', 'Air margin', 'mm')
        if study not in ('scattering', 'periodic'):
            base('Excitation', 'z0_ohm', 'Reference impedance', 'ohm')
        base('Sampling', 'field_z_mm', 'Upper field sampling plane Z', 'mm')
    base('Sampling', 'field_grid', 'Samples per plane axis')
    base('Mesh', 'mesh_edge_mm', 'Requested local mesh edge', 'mm')
    base('Mesh', 'max_tets', 'Maximum tetrahedra')
    if not thermal and study == 'driven':
        base('Mesh', 'adaptive_steps', 'Adaptive refinement steps')
        if c['adaptive_steps'] or c['sweep'] == 'adaptive':
            base('Mesh', 'convergence', 'Requested convergence tolerance')
    if study in ('periodic', 'scattering', 'waveguide'):
        add('Boundary', 'Boundary model', {'periodic': 'Periodic sides; Floquet ports', 'scattering': 'First-order scattered-field boundary', 'waveguide': 'PEC walls; TE10 ports; air-filled guide'}[study])
    coupled = study == 'driven' and a['coupled_thermal']
    for field in ADVANCED_FIELDS:
        key, group = field['key'], field['group']
        if key == 'study' or group in ('Exports', 'Import') or (field['studies'] and study not in field['studies']):
            continue
        if key == 'sparta_mode' and c['solver'] != 'SPARTA': continue
        if group == 'Patch feed' and mode != 'patch': continue
        if group == 'PCB template' and mode != 'pcb_line': continue
        if key == 'via_radius_mm' and a['line_geometry'] != 'stripline_via': continue
        if key.startswith('shunt_') and (mode != 'pcb_line' or a['shunt_component'] == 'none'): continue
        if group == 'Material':
            if key in ('conductivity_s_m', 'conductor_thickness_um', 'roughness_um') and a['conductor'] != 'finite': continue
            if key == 'er_stop' and not a[key]: continue
        if group == 'Boundary':
            if key == 'abc_order' and a['boundary'] != 'absorbing': continue
            if key == 'pml_thickness_mm' and a['boundary'] != 'pml': continue
        if group == 'Fields' and (thermal or key == 'field_z_min_mm' and a['field_layers'] == 1): continue
        if group == 'Thermal':
            if not (thermal or coupled): continue
            if key == 'coupled_thermal': continue
            if key == 'thermal_power_w' and coupled or key == 'rf_input_power_w' and not coupled: continue
            if key in ('thermal_step_s', 'density_kg_m3', 'specific_heat_j_kgk') and not a['thermal_time_s']: continue
        if group == 'Scattering':
            imported = a['import_kind'] != 'none'
            if key == 'scatter_radius_mm' and (imported or a['step_path']): continue
            if key.startswith('step_'):  # Full import identity remains in source custody / complete JSON.
                if key != 'step_unit_m' or not a['step_path'] or imported: continue
        value = requested['advanced'][key] if group == 'Optimization' else a[key]
        if key == 'conductor': value = 'Perfect electric conductor (PEC)' if value == 'pec' else 'Finite-conductivity sheet'
        unit = {'resistor': 'ohm', 'capacitor': 'pF', 'inductor': 'nH'}.get(a['shunt_component'], '') if key == 'shunt_value' else field['unit']
        add(group, field['label'], value, unit)
    if thermal or coupled:
        add('Thermal', 'Thermal boundary', 'Fixed bottom temperature; adiabatic top and sides')
    add('Solve', 'Linear solver', c['solver'])
    return rows
