"""Round-trip the main copper solve and return-review inputs by pad identity."""
from copy import deepcopy
from wayricad_runtime.setup_controls import capture_controls,validate_controls,restore_controls

TEXT=('voltage','current','source_current_limit','sink_min_voltage','sink_max_voltage',
      'edge','plating','temperature','ambient','pulse','limit','melting','latent','max_tetrahedra',
      'return_pitch','return_radius')
CHOICES=('load_mode','model_dimension','return_signal')
FLAGS=('source_pins','sink_pins','joule_feedback','auto_mesh')
OPTIONS=dict(text=TEXT,choices=CHOICES,flags=FLAGS)


def capture(frame):
    endpoints={role:(frame._terminals[control.GetSelection()]['id'] if control.GetSelection()>=0 else None)
               for role,control in (('source',frame.source),('sink',frame.sink))}
    returns={role:frame._return_pad_ids.get(control.GetStringSelection())
             for role,control in (('source',frame.return_source),('sink',frame.return_sink))}
    return deepcopy(dict(controls=capture_controls(frame,**OPTIONS),net=frame.net.GetValue(),
        endpoints=endpoints,return_nets=frame._return_selected_nets(),return_pads=returns,
        extra_sinks=frame._extra_sinks,series_request=frame._series_request,
        package_conduction=frame._package_conduction))


def validate(frame,state):
    required={'controls','net','endpoints','return_nets','return_pads','extra_sinks','series_request','package_conduction'}
    if not isinstance(state,dict) or set(state)!=required:raise ValueError('Incomplete Quick PI setup.')
    validate_controls(frame,state['controls'],**OPTIONS)
    nets=frame.inventory.get('nets',[])
    if state['net'] not in nets:raise ValueError('Saved PI net is not present in this board.')
    terminals={row['id']:row for row in frame.inventory.get('terminals',[])}
    for field in ('endpoints','return_pads'):
        values=state[field]
        if not isinstance(values,dict) or set(values)!={'source','sink'}:raise ValueError('Invalid saved endpoint mappings.')
        for identifier in values.values():
            if identifier is not None and identifier not in terminals:raise ValueError('Saved pad no longer exists: '+str(identifier))
    if not isinstance(state['return_nets'],list) or any(name not in nets for name in state['return_nets']):
        raise ValueError('Saved return nets no longer exist.')
    for identifier in state['endpoints'].values():
        if identifier is not None and terminals[identifier].get('net')!=state['net']:
            raise ValueError('Saved endpoint is no longer on the selected net.')
    for identifier in state['return_pads'].values():
        if identifier is not None and terminals[identifier].get('net') not in state['return_nets']:
            raise ValueError('Saved return pad is no longer on a selected return net.')
    if not isinstance(state['extra_sinks'],list) or not isinstance(state['package_conduction'],list):
        raise ValueError('Invalid additional sinks or package contacts.')
    if state['extra_sinks']:
        from .service import sink_requests
        sink_requests({'sinks':state['extra_sinks']})
    if state['package_conduction']:
        from wayricad_runtime.package_conduction import normalize_paths
        normalize_paths(state['package_conduction'],physics='electrical')
    from .terminals import pad_names
    for row in state['extra_sinks']:
        if not isinstance(row,dict):raise ValueError('Invalid saved additional sink.')
        for identifier in pad_names(row):
            if identifier not in terminals or terminals[identifier].get('net')!=state['net']:
                raise ValueError('An additional sink pad is missing or changed net.')
    if state['series_request'] is not None:
        request=state['series_request']
        if not isinstance(request,dict) or not isinstance(request.get('series'),list):
            raise ValueError('Invalid saved series path.')
        for key in ('source_sha256','expected_source_sha256'):
            if request.get(key) and request[key]!=frame.inventory.get('source_sha256'):
                raise ValueError('Saved series path belongs to another PCB revision. Review it again in Series.')
        pending=[request]
        while pending:
            row=pending.pop()
            if isinstance(row,list):pending.extend(row);continue
            if not isinstance(row,dict):continue
            for key in ('source_terminal','sink_terminal','from_pad','to_pad'):
                if key in row and row[key] not in terminals:raise ValueError('A saved series pad no longer exists.')
            for key in ('source_terminals','sink_terminals','from_pads','to_pads'):
                if key in row and (not isinstance(row[key],list) or any(value not in terminals for value in row[key])):
                    raise ValueError('A saved series electrode no longer exists.')
            pending.extend(value for value in row.values() if isinstance(value,(dict,list)))
    return deepcopy(state)


def restore(frame,state):
    frame.net.Set(frame.inventory.get('nets',[]));frame.net.SetValue(state['net'])
    frame._set_terminals()
    restore_controls(frame,state['controls'])
    for role,identifier in state['endpoints'].items():
        getattr(frame,role).SetSelection(next((i for i,row in enumerate(frame._terminals) if row['id']==identifier),-1))
    for i in range(frame.return_nets.GetCount()):
        frame.return_nets.Check(i,frame.return_nets.GetString(i) in state['return_nets'])
    frame._return_nets_changed()
    for role,identifier in state['return_pads'].items():
        label=next((name for name,value in frame._return_pad_ids.items() if value==identifier),'Not specified')
        getattr(frame,'return_'+role).SetStringSelection(label)
    frame._extra_sinks=deepcopy(state['extra_sinks']);frame._series_request=deepcopy(state['series_request'])
    frame._package_conduction=deepcopy(state['package_conduction'])
    if frame._series_request:frame._series_request['board_path']=frame.board_path
    frame.loads_button.SetLabel(f'Additional sinks ({len(frame._extra_sinks)})…')
    frame.package_button.SetLabel(f'Package contacts ({len(frame._package_conduction)})…')
    frame.current_label.SetLabel(('Load · A','Load · Ω','Load · W')[frame.load_mode.GetSelection()])
    frame._sync_pin_recommendations()


def bind(frame,parent,sizer):
    from wayricad_runtime.project_setup_ui import add_project_setup
    return add_project_setup(frame,parent,sizer,'quick-pi',frame.board_path,
        lambda:capture(frame),lambda state:restore(frame,state),validate=lambda state:validate(frame,state),
        invalidate=frame._invalidate,status=lambda text:frame.status.SetLabel(text))
