"""Complete editable thermal study inputs, kept separate from solver results."""
from copy import deepcopy
from wayricad_runtime.setup_controls import capture_controls,validate_controls,restore_controls

TEXT=('therm_ambient','therm_board_r','therm_explicit_h','therm_enclosure_c','therm_potting_k',
      'therm_potting_thickness','therm_potting_outer_h','therm_time_duration','therm_time_step',
      'therm_frame_interval','therm_time_initial','therm_copper_capacity','therm_dielectric_capacity',
      'therm_power_schedule','therm_sink_capacity','therm_k','therm_dielectric_k','therm_copper_k',
      'therm_plating','therm_ccx_mesh','therm_ccx_bottom','therm_ccx_executable','therm_emissivity',
      'therm_air_board','therm_air_sink','therm_sink_area','therm_mount_temp','therm_mount_r')
CHOICES=('therm_input_mode','therm_env','therm_schedule_interpolation','therm_power','therm_ja',
         'therm_jb','therm_jc','therm_limit_min','therm_limit_max','therm_model_kind','therm_model_jb','therm_blur')
FLAGS=('therm_time_enabled','therm_model_enabled','therm_auto_mesh','therm_mount_mechanical','therm_step_models')
OPTIONS=dict(text=TEXT,choices=CHOICES,flags=FLAGS,integers=('therm_grid',))
DATA=('manual_values','manual_temperature_limits','virtual_heatsinks','_component_storage',
      '_package_contacts','_copper_loss_import','_thermal_materials')


def capture(frame):
    frame.therm_inputs.commit_pending_edits()
    state=frame.therm_inputs.export_state()
    data={key:getattr(frame,key) for key in DATA}
    data['manual_values']=state['manual_values'];data['manual_temperature_limits']=state['manual_limits']
    return deepcopy(dict(controls=capture_controls(frame,**OPTIONS),
        data=data,component_inputs=state,
        mounting_ids=[frame._therm_mount_candidates[i]['id'] for i in range(frame.therm_mounts.GetCount()) if frame.therm_mounts.IsChecked(i)]))


def validate(frame,state):
    if not isinstance(state,dict) or set(state)!={'controls','data','component_inputs','mounting_ids'}:
        raise ValueError('Incomplete QuickTherm setup.')
    validate_controls(frame,state['controls'],**OPTIONS)
    data=state['data'];inputs=state['component_inputs']
    if not isinstance(data,dict) or set(data)!=set(DATA) or not isinstance(inputs,dict):
        raise ValueError('Invalid component thermal inputs.')
    if set(inputs)!={'manual_values','manual_limits','references'}:
        raise ValueError('Unsupported component input state.')
    if data['manual_values']!=inputs['manual_values'] or data['manual_temperature_limits']!=inputs['manual_limits']:
        raise ValueError('Saved thermal component overrides disagree with the input table.')
    refs=set(frame.inventory.get('component_references',[]))
    if not isinstance(inputs['references'],list) or any(ref not in refs for ref in inputs['references']):
        raise ValueError('A saved thermal component no longer exists on this board.')
    for mapping in (inputs['manual_values'],inputs['manual_limits'],data['manual_values'],
                    data['manual_temperature_limits'],data['virtual_heatsinks'],data['_component_storage']):
        if not isinstance(mapping,dict) or any(ref not in refs for ref in mapping):
            raise ValueError('Saved thermal input refers to an unknown component.')
    from .component_inputs import ComponentInputsModel,QUANTITIES
    merged=deepcopy(inputs['manual_values'])
    for ref,values in inputs['manual_limits'].items():
        if not isinstance(values,dict):raise ValueError('Invalid manual temperature limits.')
        merged.setdefault(ref,{}).update(values)
    for values in merged.values():
        if not isinstance(values,dict) or set(values)-set(QUANTITIES):raise ValueError('Unsupported thermal input quantity.')
    model=ComponentInputsModel(frame.inventory,manual_values=merged,selected_references=inputs['references'])
    model.validate()
    contacts=data['_package_contacts']
    if not isinstance(contacts,list) or any(not isinstance(row,dict) or row.get('reference') not in refs for row in contacts):
        raise ValueError('A saved thermal contact refers to an unknown component.')
    if contacts:
        from wayricad_runtime.package_conduction import normalize_paths
        normalize_paths(contacts,physics='thermal')
    from .quick_therm import _normalize_heatsinks
    environment='vacuum' if state['controls']['choices']['therm_env']=='Vacuum' else 'air'
    _normalize_heatsinks(data['virtual_heatsinks'],environment)
    from wayricad_runtime.thermal_materials import validate_material_selection
    materials=data['_thermal_materials']
    if not isinstance(materials,dict) or set(materials)-{'dielectric','copper'}:
        raise ValueError('Invalid saved thermal material selections.')
    for entry in materials.values():
        if not isinstance(entry,dict) or set(entry)!={'selection','bindings'} or not isinstance(entry['bindings'],dict):
            raise ValueError('Invalid saved material binding.')
        validate_material_selection(entry['selection'])
    available={row['id'] for row in frame._therm_mount_candidates}
    if not isinstance(state['mounting_ids'],list) or any(value not in available for value in state['mounting_ids']):
        raise ValueError('A saved mounting contact no longer exists.')
    losses=data['_copper_loss_import']
    if losses is not None and (not isinstance(losses,dict) or losses.get('source_sha256')!=frame.inventory.get('source_sha256')):
        raise ValueError('Saved imported PI losses belong to another board revision. Reimport current losses before loading this setup.')
    return deepcopy(state)


def restore(frame,state):
    restore_controls(frame,state['controls'])
    for key,value in state['data'].items():setattr(frame,key,deepcopy(value))
    inputs=state['component_inputs'];frame.manual_values=deepcopy(inputs['manual_values'])
    frame.manual_temperature_limits=deepcopy(inputs['manual_limits'])
    for i in range(frame.therm_refs.GetCount()):frame.therm_refs.Check(i,frame.therm_refs.GetString(i) in inputs['references'])
    for i,row in enumerate(frame._therm_mount_candidates):frame.therm_mounts.Check(i,row['id'] in state['mounting_ids'])
    merged=deepcopy(frame.manual_values)
    for ref,values in inputs['manual_limits'].items():merged.setdefault(ref,{}).update(values)
    frame.therm_inputs.load(frame.inventory,frame._thermal_field_map(),merged,
        inputs['references'],frame._temperature_field_map())
    frame._component_storage_board_sha=frame.inventory.get('source_sha256')
    frame._package_contacts_board_sha=frame.inventory.get('source_sha256')
    frame._update_thermal_scope();frame._therm_controls()


def bind(frame,parent,sizer):
    from wayricad_runtime.project_setup_ui import add_project_setup
    return add_project_setup(frame,parent,sizer,'quick-therm',frame.board_path,
        lambda:capture(frame),lambda state:restore(frame,state),validate=lambda state:validate(frame,state),
        invalidate=frame._invalidate_thermal,status=lambda text:frame.status.SetLabel(text))
