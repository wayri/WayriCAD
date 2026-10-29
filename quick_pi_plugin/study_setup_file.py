"""Versioned editable study snapshots for Quick PI's independent dialogs."""
from __future__ import annotations

import copy
import json
import math
from collections import Counter
from pathlib import Path


MODES={'ACStudyDialog':'ac','BatchStudyDialog':'batch',
       'ElectrothermalStudyDialog':'electrothermal','PITransientStudyDialog':'pi-transient',
       'TransientStudyDialog':'transient','PdnImpedanceDialog':'pdn'}


def _fields(controls):
    return {key:control.GetValue() for key,control in controls.items()}


def _grid(grid):
    if grid.IsCellEditControlEnabled():
        grid.SaveEditControlValue();grid.DisableCellEditControl()
    return [[grid.GetCellValue(i,j) for j in range(grid.GetNumberCols())]
            for i in range(grid.GetNumberRows())]


def capture(dialog):
    """Retain both active and alternate controls, including incomplete drafts."""
    mode=MODES[type(dialog).__name__]
    state=dict(mode=mode)
    if mode=='ac':
        state.update(model=copy.deepcopy(dialog.model),fields=_fields(dialog.fields),
            conductors=_grid(dialog.conductors),harmonics=_grid(dialog.harmonics),
            quick_fields=_fields(dialog.quick_fields),preset=dialog.quick_preset.GetStringSelection(),
            setup_mode=dialog.setup_mode.GetSelection(),quick_dirty=dialog._quick_dirty)
    elif mode=='batch':state.update(study_text=dialog.setup.GetValue())
    elif mode=='electrothermal':
        state.update(model_kind=dialog._kind(),study_text=dialog.setup.GetValue())
    elif mode=='pdn':state.update(fields=_fields(dialog.fields),capacitors=_grid(dialog.caps))
    else:
        state.update(kind=dialog.kind,parameters=_fields(dialog.parameters),rows=_grid(dialog.rows))
        if mode=='pi-transient':
            state.update(quick_fields=_fields(dialog.quick_fields),quick_rows=_grid(dialog.quick_rows),
                advanced=dialog.advanced.GetValue(),banks={str(i):copy.deepcopy(bank) for i,bank in dialog._banks.items()},
                rise_times={str(i):value for i,value in dialog._rise_times.items()},
                signal_net=dialog._signal_net,return_nets=list(dialog._cap_returns))
    return state


def _text_fields(values,keys):
    if not isinstance(values,dict) or set(values)!=set(keys) or any(not isinstance(v,str) or len(v)>65536 for v in values.values()):
        raise ValueError('The setup input fields do not match this study editor.')


def _rows(rows,columns,limit,minimum=0):
    if (not isinstance(rows,list) or not minimum<=len(rows)<=limit or
            any(not isinstance(row,list) or len(row)!=columns or
                any(not isinstance(cell,str) or len(cell)>65536 for cell in row) for row in rows)):
        raise ValueError('The saved study table has unsupported dimensions or cells.')


def validate(dialog,state):
    """Validate the complete mode and canonical model before any controls move."""
    mode=MODES[type(dialog).__name__]
    keys={'ac':{'model','fields','conductors','harmonics','quick_fields','preset','setup_mode','quick_dirty'},
          'batch':{'study_text'},'electrothermal':{'model_kind','study_text'},'pdn':{'fields','capacitors'},
          'transient':{'kind','parameters','rows'},
          'pi-transient':{'kind','parameters','rows','quick_fields','quick_rows','advanced','banks','rise_times','signal_net','return_nets'}}[mode]|{'mode'}
    if not isinstance(state,dict) or set(state)!=keys or state.get('mode')!=mode:
        raise ValueError('Choose a setup file for this '+mode+' study, not another Quick PI workflow.')
    state=copy.deepcopy(state);mode=state['mode']
    if mode=='ac':
        from .ac_cli import parse_study
        parse_study(json.dumps(state['model'],allow_nan=False).encode())
        _text_fields(state['fields'],dialog.fields);_text_fields(state['quick_fields'],dialog.quick_fields)
        _rows(state['conductors'],6,16);_rows(state['harmonics'],2,32)
        if state['preset'] not in dialog.quick_preset.GetStrings() or type(state['setup_mode']) is not int or state['setup_mode'] not in (0,1) or type(state['quick_dirty']) is not bool:
            raise ValueError('Unsupported AC recipe or setup mode.')
    elif mode=='batch':
        from .batch import parse_study
        if not isinstance(state['study_text'],str):raise ValueError('Batch study must contain JSON text.')
        study=parse_study(state['study_text'].encode())
        _board_assignments(dialog,study)
    elif mode=='electrothermal':
        from .electrothermal_cli import parse_envelope
        if not isinstance(state['study_text'],str):raise ValueError('Electrothermal study must contain JSON text.')
        envelope=parse_envelope(('{"mode":'+json.dumps(state['model_kind'])+',"study":'+state['study_text']+'}').encode())
        if dialog.steady_only and envelope['mode']!='steady':
            raise ValueError('This saved-board feedback editor accepts steady studies only.')
    elif mode=='pdn':
        _text_fields(state['fields'],dialog.fields);_rows(state['capacitors'],5,32,1)
    else:
        if state['kind']!=dialog.kind:raise ValueError('The transient setup belongs to another solver.')
        _text_fields(state['parameters'],dialog.parameters)
        _rows(state['rows'],dialog.rows.GetNumberCols(),64,1)
        if mode=='pi-transient':
            _text_fields(state['quick_fields'],dialog.quick_fields)
            _rows(state['quick_rows'],dialog.quick_rows.GetNumberCols(),64,1)
            if type(state['advanced']) is not bool:raise ValueError('Advanced mode must be true or false.')
            if (not isinstance(state['signal_net'],str) or not isinstance(state['return_nets'],list) or
                    any(not isinstance(net,str) for net in state['return_nets']) or
                    len(set(state['return_nets']))!=len(state['return_nets'])):
                raise ValueError('Invalid capacitor candidate net context.')
            if dialog._cap_terminals:
                nets={row.get('net') for row in dialog._cap_terminals}
                if ((state['signal_net'] and state['signal_net'] not in nets) or
                        any(net not in nets for net in state['return_nets'])):
                    raise ValueError('The saved capacitor candidate nets no longer exist.')
            _banks(state,max(len(state['rows']),len(state['quick_rows'])))
    return state


def _board_assignments(dialog,study):
    """Reject disappeared exact pads/nets when a native inventory is available."""
    terminals=dialog.inventory.get('terminals',[])
    if not terminals:return
    names={row['id']:row['net'] for row in terminals}
    counts=Counter(row.get('label') for row in terminals)
    for row in terminals:
        label=row.get('label')
        if label and counts[label]==1:names[label]=row['net']
    nets={row['net'] for row in terminals}
    for case in study['cases']:
        electrical=case['electrical'];net=electrical['net']
        if net not in nets:raise ValueError('Saved study net is unavailable: '+net)
        from .terminals import source_names
        pins=source_names(electrical)
        sinks=electrical.get('sinks',[dict(terminal=electrical.get('sink_terminal'))])
        for sink in sinks:pins+=sink.get('terminals') or [sink.get('terminal')]
        if any(pin not in names or names[pin]!=net for pin in pins):
            raise ValueError('A saved source/load pad no longer belongs to its rail.')


def _banks(state,count):
    banks=state['banks'];rise=state['rise_times']
    from .transient import MAX_SHUNTS_PER_LOAD,MAX_SHUNT_BRANCHES
    if not isinstance(banks,dict) or not isinstance(rise,dict):raise ValueError('Invalid saved shunt banks.')
    seen=set()
    for key,bank in banks.items():
        if not isinstance(key,str) or not key.isdecimal() or str(int(key))!=key or not 0<=int(key)<count:
            raise ValueError('A saved capacitor bank has no corresponding load row.')
        if not isinstance(bank,list) or not 1<=len(bank)<=MAX_SHUNTS_PER_LOAD:raise ValueError('Invalid capacitor branch count.')
        for row in bank:
            if not isinstance(row,dict) or set(row)!={'id','capacitance_F','esr_ohm','esl_H'}:
                raise ValueError('Invalid saved capacitor branch fields.')
            identifier=row['id']
            if not isinstance(identifier,str) or not identifier or identifier in seen:raise ValueError('Capacitor branch IDs must be unique.')
            seen.add(identifier)
            if len(seen)>MAX_SHUNT_BRANCHES:raise ValueError('Too many capacitor branches for this model.')
            for name in ('capacitance_F','esr_ohm','esl_H'):
                value=row[name]
                if type(value) not in (int,float) or not math.isfinite(value) or value<0 or name=='capacitance_F' and value==0:
                    raise ValueError('Capacitor C/ESR/ESL must retain valid finite physical values.')
    for key,value in rise.items():
        if key not in banks or type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise ValueError('Invalid capacitor load rise-time assignment.')


def _write_fields(controls,values):
    for key,control in controls.items():control.ChangeValue(values[key])


def _write_grid(grid,rows):
    if grid.IsCellEditControlEnabled():grid.DisableCellEditControl()
    if grid.GetNumberRows():grid.DeleteRows(0,grid.GetNumberRows())
    if rows:grid.AppendRows(len(rows))
    for i,row in enumerate(rows):
        for j,value in enumerate(row):grid.SetCellValue(i,j,value)


def restore(dialog,state):
    """Apply only editor inputs and invalidate prior computed results."""
    mode=state['mode']
    if mode=='ac':
        dialog._loading=True
        try:
            dialog.model=copy.deepcopy(state['model']);_write_fields(dialog.fields,state['fields'])
            _write_grid(dialog.conductors,state['conductors']);_write_grid(dialog.harmonics,state['harmonics'])
            _write_fields(dialog.quick_fields,state['quick_fields']);dialog.quick_preset.SetStringSelection(state['preset'])
            dialog.setup_mode.SetSelection(state['setup_mode']);dialog._quick_dirty=state['quick_dirty']
            dialog.advanced.Collapse(state['setup_mode']==0)
        finally:dialog._loading=False
        dialog.input_path=dialog.input_sha=None;dialog._invalidate();dialog._schedule_preview()
    elif mode=='batch':
        dialog.setup.ChangeValue(state['study_text']);dialog.changed()
    elif mode=='electrothermal':
        dialog.mode.SetSelection(0 if state['model_kind']=='steady' else 1)
        dialog.setup.ChangeValue(state['study_text']);dialog._changed()
    elif mode=='pdn':
        dialog._loading=True
        try:_write_fields(dialog.fields,state['fields']);_write_grid(dialog.caps,state['capacitors'])
        finally:dialog._loading=False
        dialog._input_path=None;dialog._changed()
    else:
        _write_fields(dialog.parameters,state['parameters']);_write_grid(dialog.rows,state['rows'])
        if mode=='pi-transient':
            _write_fields(dialog.quick_fields,state['quick_fields']);_write_grid(dialog.quick_rows,state['quick_rows'])
            dialog._banks={int(i):copy.deepcopy(bank) for i,bank in state['banks'].items()}
            dialog._rise_times={int(i):value for i,value in state['rise_times'].items()}
            dialog._signal_net=state['signal_net'];dialog._cap_returns=tuple(state['return_nets'])
            advanced=state['advanced'];dialog.advanced.SetValue(advanced);dialog.quick_body.Show(not advanced)
            for item in dialog._advanced_objects:dialog._setup_form.Show(item,advanced)
            dialog._setup_form.GetItem(dialog.quick_panel).SetProportion(0 if advanced else 1)
            dialog._sync_bank_cells();dialog._input_path=dialog._input_sha=None
        dialog._changed()
    dialog.Layout()
    if hasattr(dialog,'book'):
        page=dialog.book.GetPage(0);page.Layout()
        if hasattr(page,'FitInside'):page.FitInside()


def add_study_setup(dialog,plugin,board_path):
    """Attach shared file actions to a known PI study; return None otherwise."""
    if type(dialog).__name__ not in MODES:return None
    if getattr(dialog,'_project_setup_actions',None) is not None:return dialog._project_setup_actions
    from wayricad_runtime.project_setup_ui import add_project_setup
    dialog._setup_board_path=Path(board_path).resolve()
    actions=add_project_setup(dialog,dialog,dialog.GetSizer(),plugin,board_path,
        lambda:capture(dialog),lambda state:restore(dialog,state),validate=lambda state:validate(dialog,state),
        status=dialog.status.SetLabel)
    actions.default_name=Path(board_path).stem+'.'+plugin+'.'+MODES[type(dialog).__name__]+'.setup.json'
    dialog._project_setup_actions=actions;dialog.Layout()
    return actions


def project_directory(dialog):
    """Resolve the originating PCB folder for the existing raw-model choosers."""
    path=getattr(dialog,'_setup_board_path',None) or getattr(dialog,'board_path',None)
    return str(Path(path).resolve().parent) if path else ''
