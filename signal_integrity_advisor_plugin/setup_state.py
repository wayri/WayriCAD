"""Complete editable Quick SI inputs, separate from immutable result archives."""
from __future__ import annotations

import copy
import math


def capture(panel):
    """Snapshot main inputs, drafted studies, return pins and reviewed IBIS choices."""
    ibis = panel.ibis
    paths={assignment['path'] for assignment in ibis._assignments.values()}
    paths.update(catalog['path'] for catalog in ibis._current.values() if catalog)
    return dict(fields={key: control.GetValue() for key, control in panel.fields.items()},
        eye_enabled=panel.eye_enabled.GetValue(),
        returns=dict(nets=panel.return_setup.selected_nets(),
            source=panel.return_setup.terminal_value(panel.return_source),
            sink=panel.return_setup.terminal_value(panel.return_sink)),
        study_nets=[panel.study_nets.GetString(i) for i in panel.study_nets.GetCheckedItems()],
        study_cases=copy.deepcopy(panel.study_cases), crosstalk_pairs=copy.deepcopy(panel.crosstalk_pairs),
        ibis=dict(assignments=[dict(key=list(key), assignment=copy.deepcopy(value))
            for key, value in sorted(ibis._assignments.items())],
            blocked=[list(key) for key in sorted(ibis._blocked_keys)],
            catalogs={path: ibis._catalogs[path]['sha256'] for path in sorted(paths)},
            current={role: catalog['path'] if catalog else None for role, catalog in ibis._current.items()},
            choices={role: {key: ibis._selected(role, key) for key in ('component','pin','model','corner')}
                for role in ('source','sink')}))


def _names(values, available, label):
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
        raise ValueError(label+' must contain distinct names.')
    missing = set(values)-set(available)
    if missing:
        raise ValueError(label+' no longer exists on this board: '+', '.join(sorted(missing)))


def validate(panel, state):
    """Validate all choices and external IBIS fingerprints before changing widgets.

    Drafts may contain blank numeric fields or unassigned route endpoints. They
    remain drafts and the normal solver validation still applies when run.
    """
    from .study import CASE_KEYS, INPUTS, cases_from_config
    from .crosstalk import checked_pairs
    from .ibis_models import assignment_from_catalog, load_ibis
    if not isinstance(state, dict) or set(state) != {'fields','eye_enabled','returns','study_nets','study_cases','crosstalk_pairs','ibis'}:
        raise ValueError('Unsupported or incomplete Quick SI setup fields.')
    state = copy.deepcopy(state)
    fields = state['fields']
    # Older setups predate explicit receiver/via parasitics. Blank means no
    # reviewed via equivalent; it must not revive the former ideal-line eye.
    if isinstance(fields, dict):
        for key in ('eye_load_pf','eye_via_l_nh','eye_via_c_pf'):
            fields.setdefault(key, '')
    if not isinstance(fields, dict) or set(fields) != set(panel.fields) or any(not isinstance(v,str) for v in fields.values()):
        raise ValueError('Quick SI setup must contain every input field as text.')
    if fields['net'] and fields['net'] not in panel._net_names:
        raise ValueError('The saved signal net no longer exists on this board.')
    pads = panel._setup_pads.get(fields['net'], [])
    for key in ('start','end'):
        if fields[key] and fields[key] not in pads: raise ValueError('Saved '+key+' pad no longer belongs to the signal net.')
    layers = panel.fields['reference'].GetStrings()
    if fields['reference'] not in layers: raise ValueError('Saved reference layer is unavailable.')
    for key, value in fields.items():
        if key in ('net','start','end','reference') or not value.strip(): continue
        try: number = float(value)
        except ValueError: raise ValueError(key+' must be numeric or blank.') from None
        if not math.isfinite(number): raise ValueError(key+' must be finite.')
    if type(state['eye_enabled']) is not bool: raise ValueError('Eye enable must be true or false.')
    returns = state['returns']
    if not isinstance(returns, dict) or set(returns) != {'nets','source','sink'}: raise ValueError('Invalid saved return setup.')
    _names(returns['nets'], set(panel._net_names)-{fields['net']}, 'Return nets')
    _check_return_pads(panel, returns['nets'], [returns['source'],returns['sink']])
    _names(state['study_nets'], panel._net_names, 'Study nets')
    cases = state['study_cases']
    if not isinstance(cases,list) or len(cases)>64: raise ValueError('A setup supports at most 64 study cases.')
    if cases: cases_from_config(dict(cases=cases,crosstalk=state['crosstalk_pairs']))
    else: checked_pairs(dict(crosstalk=state['crosstalk_pairs']),cases)
    for case in cases:
        if not isinstance(case,dict) or set(case)-CASE_KEYS: raise ValueError('Unknown saved study case fields.')
        if case.get('net') not in panel._net_names: raise ValueError('A study net no longer exists on this board.')
        for key in ('start','end'):
            value = case.get(key,'')
            if not isinstance(value,str) or (value and value not in panel._setup_pads[case['net']]):
                raise ValueError('A saved study pad no longer belongs to its net.')
        if case.get('reference','Auto') not in layers: raise ValueError('A study reference layer is unavailable.')
        inputs = case.get('inputs',{})
        if not isinstance(inputs,dict) or set(inputs)-INPUTS: raise ValueError('Unknown study input fields.')
        for key,value in inputs.items():
            if key.startswith('return_'): continue
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value)):
                raise ValueError('Study numerical assumptions must be finite numbers or null.')
        return_nets=inputs.get('return_nets',[])
        _names(return_nets,set(panel._net_names)-{case['net']},'Study return nets')
        roles=inputs.get('return_terminal_roles',{})
        if not isinstance(roles,dict) or set(roles)-{'source','load'}: raise ValueError('Invalid study return roles.')
        _check_return_pads(panel,return_nets,inputs.get('return_terminal_ids',[])+list(roles.values()))
    ibis=state['ibis']
    if not isinstance(ibis,dict) or set(ibis)!={'assignments','blocked','catalogs','current','choices'}:
        raise ValueError('Invalid saved IBIS setup.')
    if not isinstance(ibis['catalogs'],dict) or len(ibis['catalogs'])>64: raise ValueError('Too many saved IBIS catalogs.')
    catalogs={}
    for path,digest in ibis['catalogs'].items():
        catalog=load_ibis(path)
        if catalog['sha256']!=digest: raise ValueError('IBIS model changed since this setup was saved: '+path)
        catalogs[path]=catalog
    seen=set()
    if not isinstance(ibis['assignments'],list) or len(ibis['assignments'])>1024: raise ValueError('Invalid IBIS assignments.')
    for row in ibis['assignments']:
        if not isinstance(row,dict) or set(row)!={'key','assignment'}: raise ValueError('Invalid IBIS assignment.')
        key=_ibis_key(panel,row['key'])
        if key in seen: raise ValueError('Duplicate IBIS endpoint assignment.')
        seen.add(key); assignment=row['assignment']
        if not isinstance(assignment,dict) or assignment.get('path') not in catalogs: raise ValueError('Missing saved IBIS catalog.')
        expected=assignment_from_catalog(catalogs[assignment['path']],assignment.get('component'),assignment.get('pin'),assignment.get('model'),key[1],assignment.get('corners'))
        if assignment!=expected: raise ValueError('IBIS assignment does not match its catalog or endpoint role.')
    if not isinstance(ibis['blocked'],list): raise ValueError('Invalid blocked IBIS assignments.')
    for key in ibis['blocked']: _ibis_key(panel,key)
    if not isinstance(ibis['current'],dict) or set(ibis['current'])!={'source','sink'}: raise ValueError('Invalid active IBIS catalogs.')
    if any(path is not None and path not in catalogs for path in ibis['current'].values()): raise ValueError('Missing active IBIS catalog.')
    if not isinstance(ibis['choices'],dict) or set(ibis['choices'])!={'source','sink'}: raise ValueError('Invalid IBIS choices.')
    from .ibis_ui import model_choices
    for role,choice in ibis['choices'].items():
        if not isinstance(choice,dict) or set(choice)!={'component','pin','model','corner'} or any(not isinstance(v,str) for v in choice.values()):
            raise ValueError('Invalid IBIS selector fields.')
        catalog=catalogs.get(ibis['current'][role]); component=choice['component']; pin=choice['pin']
        if choice['corner'] not in ('typ','min','max'): raise ValueError('Invalid IBIS corner.')
        if component and (not catalog or component not in catalog['components']): raise ValueError('IBIS component unavailable.')
        if pin and (not component or pin not in catalog['components'][component]['pins']): raise ValueError('IBIS pin unavailable.')
        if choice['model'] and (not pin or choice['model'] not in model_choices(catalog,component,pin,role)): raise ValueError('IBIS model unavailable.')
    return state


def _check_return_pads(panel, nets, pads):
    if not isinstance(pads,list): raise ValueError('Return pads must be a list.')
    valid={row[key] for row in panel._setup_terminals if row['net'] in nets for key in ('label','id')}
    if any(value is not None and (not isinstance(value,str) or value not in valid) for value in pads):
        raise ValueError('A saved return pad no longer belongs to its selected return nets.')


def _ibis_key(panel, key):
    if not isinstance(key,list) or len(key)!=3 or any(not isinstance(v,str) for v in key): raise ValueError('Invalid IBIS endpoint key.')
    net,role,pad=key
    if role not in ('source','sink') or net not in panel._setup_pads or pad not in panel._setup_pads[net]:
        raise ValueError('IBIS assignment endpoint no longer exists on this board.')
    return tuple(key)


def restore(panel, state):
    """Apply a validated setup; the shared controller rolls back on failure."""
    from .return_setup_ui import NO_REVIEW, UNSPECIFIED
    from .ibis_models import load_ibis
    saved=state['ibis']
    # Recheck external model custody before touching controls or prior results.
    catalogs={path:load_ibis(path) for path in saved['catalogs']}
    if any(catalogs[path]['sha256']!=digest for path,digest in saved['catalogs'].items()):
        raise ValueError('IBIS model changed while loading this setup.')
    fields=state['fields']
    panel.net_search.ChangeValue(''); panel.fields['net'].Set(panel._net_names)
    panel.fields['net'].SetValue(fields['net'])
    pads=panel._setup_pads.get(fields['net'],[])
    for key in ('start','end'): panel.fields[key].Set(pads)
    for key,value in fields.items():
        control=panel.fields[key]
        if key not in ('net','start','end','reference'): control.ChangeValue(value)
        else: control.SetValue(value)
    panel.eye_enabled.SetValue(state['eye_enabled'])
    returns=panel.return_setup; returns.set_context(fields['net'],fields['start'],fields['end'])
    returns._setting=True
    try:
        for i in range(returns.nets.GetCount()): returns.nets.Check(i,returns.nets.GetString(i) in state['returns']['nets'])
        returns.primary.SetValue(next(iter(state['returns']['nets']),NO_REVIEW)); returns._refresh_pads()
        for key,control in (('source',returns.source),('sink',returns.sink)):
            value=state['returns'][key]
            control.SetValue(next((text for text,identifier in returns._terminal_values.items() if identifier==value),UNSPECIFIED))
        returns._summary()
    finally: returns._setting=False
    panel.study_cases=copy.deepcopy(state['study_cases']); panel.crosstalk_pairs=copy.deepcopy(state['crosstalk_pairs'])
    for i in range(panel.study_nets.GetCount()): panel.study_nets.Check(i,panel.study_nets.GetString(i) in state['study_nets'])
    panel.study_edit.SetLabel('Edit study cases ('+str(len(panel.study_cases))+')…')
    panel.changed(None)
    ibis=panel.ibis
    ibis._catalogs=catalogs
    ibis._assignments={tuple(row['key']):copy.deepcopy(row['assignment']) for row in saved['assignments']}
    ibis._blocked_keys={tuple(key) for key in saved['blocked']}
    ibis._current={role:catalogs.get(path) for role,path in saved['current'].items()}
    ibis.set_context(fields['net'],fields['start'],fields['end'])
    for role,choice in saved['choices'].items():
        ibis._serial[role]+=1
        controls=ibis._controls[role]
        controls['component'].SetValue(choice['component'])
        ibis._show_pin_model(role,choice['component'])
        controls['pin'].SetValue(choice['pin'])
        from .ibis_ui import model_choices
        models=model_choices(ibis._current[role],choice['component'],choice['pin'],role) if choice['pin'] else []
        controls['model'].Set(models); controls['model'].SetValue(choice['model']); controls['corner'].SetValue(choice['corner'])
        ibis._capture(role,notify=False)
    panel.inputs.FitInside(); panel.Layout()
