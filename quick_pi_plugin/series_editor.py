"""Native series-path editor backed by the same bounded Quick PI parser."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
from copy import deepcopy


def compatible_components(inventory, net, used=()):
    """Two-pad components that bridge the current net to a different net."""
    grouped = {}
    for row in inventory.get('terminals', []):
        label = str(row.get('label', ''))
        if '.' in label:
            reference, _ = label.rsplit('.', 1)
            grouped.setdefault(reference, []).append(row)
    return [(reference, next(row['net'] for row in pads if row['net'] != net))
            for reference, pads in sorted(grouped.items())
            if reference not in used and len(pads) == 2 and len({row['id'] for row in pads}) == 2
            and sum(row['net'] == net for row in pads) == 1]


def build_command(source_label, sink_label, branches):
    """Build a quoted console path; parse_command remains the authority."""
    tokens = ['run', 'pi', source_label]
    for branch in branches:
        if not branch.get('reference') or not branch.get('model') or ':' in branch['reference']:
            raise ValueError('Each series row needs a component reference and model.')
        if 'from_pad' in branch or 'to_pad' in branch:
            if not branch.get('from_pad') or not branch.get('to_pad'):
                raise ValueError('An explicit series stage needs both reviewed pad identities.')
            tokens.extend([branch['from_pad'], branch['model'], branch['to_pad']])
        else:
            tokens.append(branch['reference'] + ':' + branch['model'])
    tokens.append(sink_label)
    return shlex.join(tokens)


def display_path_command(data, inventory):
    """Show reviewed reference.pin labels while the saved path retains IDs."""
    from .console import terminal_aliases
    aliases=terminal_aliases(inventory)
    def label(value):
        matches=[row for row in inventory.get('terminals',[]) if value in (row.get('id'),row.get('label'))]
        return aliases[str(matches[0]['id'])] if len(matches)==1 else value
    branches=[]
    for branch in data.get('branches',[]):
        shown=dict(branch)
        for key in ('from_pad','to_pad'):
            if key in shown:shown[key]=label(shown[key])
        branches.append(shown)
    return build_command(label(data.get('source','')),label(data.get('sink','')),branches)


def grouped_pad_preview(request, inventory):
    """Show reviewed multi-pad electrodes and every selected parallel branch."""
    from .console import terminal_aliases
    aliases=terminal_aliases(inventory)
    lines=[]
    for title,key in (('Source','source_terminals'),('Sink','sink_terminals')):
        ids=request.get(key,[])
        if len(ids)>1:lines.append(title+' pads: '+', '.join(aliases.get(str(identifier),str(identifier)) for identifier in ids))
    for number,stage in enumerate(request.get('series',[]),1):
        for element in [stage,*stage.get('parallel',[])]:
            prefix='Stage '+str(number)+' '+str(element.get('id',''))
            if element is not stage:
                incoming=element.get('from_pads',[element.get('from_pad')])
                outgoing=element.get('to_pads',[element.get('to_pad')])
                describe=lambda ids:', '.join(aliases.get(str(value),str(value)) for value in ids if value)
                model=[]
                if element.get('resistance_ohm'):model.append(str(element['resistance_ohm'])+' Ω')
                if element.get('inductance_h'):model.append(str(element['inductance_h'])+' H')
                lines.append(prefix+' parallel: '+describe(incoming)+' → '+describe(outgoing)+
                             (' · '+', '.join(model) if model else ''))
                continue
            for title,key in (('incoming','from_pads'),('outgoing','to_pads')):
                ids=element.get(key,[])
                if len(ids)>1:
                    lines.append(prefix+' '+title+' pads: '+
                                 ', '.join(aliases.get(str(identifier),str(identifier)) for identifier in ids))
    return lines


def current_pad_group(rows, anchor, include_peers):
    """One current electrode: only exact-footprint pads on the anchor net."""
    if not include_peers:return [anchor]
    from .pin_units import peers
    return [anchor,*[row['id'] for row in peers(rows,anchor)]]


def path_from_command(command, inventory, existing=None):
    """Turn a validated manual path into the unchanged schema-1 editor format."""
    from .console import parse_command
    parsed=parse_command(command,inventory)
    if parsed.get('action')!='solve':raise ValueError('Enter a run pi source-to-sink path.')
    tokens=shlex.split(command)
    args=tokens[2:]
    if args and args[0] in inventory.get('nets',[]):args=args[1:]
    middle=args[1:-1]
    branches=[];index=0
    for solved in parsed['series']:
        token=middle[index]
        if ':' in token and not any(token in (row.get('id'),row.get('label')) for row in inventory.get('terminals',[])):
            parts=token.split(':');model='+'.join(parts[1:]);index+=1
        else:
            model=middle[index+1];index+=3
        branches.append({'reference':solved['id'],'from_pad':solved['from_pad'],
                         'to_pad':solved['to_pad'],'model':model})
    if index!=len(middle):raise ValueError('Manual path has unmatched series tokens.')
    def label(identifier):
        rows=[row for row in inventory.get('terminals',[]) if row.get('id')==identifier]
        if len(rows)!=1:raise ValueError('Manual path terminal is no longer in the saved board.')
        return identifier if sum(row.get('label')==rows[0]['label'] for row in inventory['terminals'])>1 else rows[0]['label']
    data={'schema':1,'source':label(parsed['source_terminal']),
          'sink':label(parsed['sink_terminal']),'branches':branches}
    if isinstance(existing,dict):
        try:old=parse_saved_path(existing,inventory)
        except ValueError:old={}
        for key,anchor in (('source_terminals','source_terminal'),('sink_terminals','sink_terminal')):
            if old.get(anchor)==parsed[anchor]:
                if key in existing:data[key]=deepcopy(existing[key])
            else:
                group=current_pad_group(inventory['terminals'],parsed[anchor],True)
                if len(group)>1:data[key]=group
        old_stages=old.get('series',[])
        for branch,stage in zip(branches,parsed['series']):
            previous=next((i for i,row in enumerate(old_stages)
                           if (row['id'],row['from_pad'],row['to_pad'])==
                              (stage['id'],stage['from_pad'],stage['to_pad'])),None)
            if previous is not None:
                for key in ('from_pads','to_pads','parallel'):
                    if key in existing['branches'][previous]:
                        branch[key]=deepcopy(existing['branches'][previous][key])
            else:
                for key,anchor in (('from_pads','from_pad'),('to_pads','to_pad')):
                    group=current_pad_group(inventory['terminals'],stage[anchor],True)
                    if len(group)>1:branch[key]=group
    parse_saved_path(data,inventory)
    return data


def draft_from_request(request, inventory):
    """Seed the editor from a restored solve request without changing schema 1."""
    if not isinstance(request,dict) or not isinstance(request.get('series'),list):
        raise ValueError('A restored series solve request is required.')
    def row_for(value):
        matches=[row for row in inventory.get('terminals',[])
                 if value in (row.get('id'),row.get('label'))]
        if len(matches)!=1:raise ValueError('Restored series pad is missing or ambiguous: '+str(value))
        return matches[0]
    def token(value):
        row=row_for(value)
        return row['id'] if sum(item.get('label')==row['label'] for item in inventory['terminals'])>1 else row['label']
    def model(branch):
        if isinstance(branch.get('model'),str) and branch['model'].strip():return branch['model']
        if branch.get('fixed_drop_v') is not None:return repr(float(branch['fixed_drop_v']))+'V'
        diode=branch.get('diode')
        if isinstance(diode,dict):
            return ('diode(Vf='+repr(float(diode['vf_ref_v']))+'V,Iref='+
                    repr(float(diode['reference_current_a']))+'A,n='+
                    repr(float(diode['ideality']))+',T='+repr(float(diode['temperature_c']))+'C)')
        values=[]
        if branch.get('resistance_ohm'):values.append(repr(float(branch['resistance_ohm']))+'Ω')
        if branch.get('inductance_h'):values.append(repr(float(branch['inductance_h']))+'H')
        if not values:raise ValueError('Restored series component has no explicit model.')
        return '+'.join(values)
    branches=[]
    for stage in request['series']:
        if not isinstance(stage,dict):raise ValueError('Restored series stage is malformed.')
        entry,exit_pad=row_for(stage.get('from_pad')),row_for(stage.get('to_pad'))
        reference=entry.get('reference',entry['label'].rsplit('.',1)[0])
        branch={'reference':reference,'from_pad':entry['id'],'to_pad':exit_pad['id'],
                'model':model(stage)}
        for key in ('from_pads','to_pads'):
            if key in stage:branch[key]=deepcopy(stage[key])
        if stage.get('parallel'):
            parallel=[]
            for part in stage['parallel']:
                left,right=row_for(part.get('from_pad')),row_for(part.get('to_pad'))
                owner=left.get('footprint_uuid')
                if not owner or owner!=right.get('footprint_uuid'):
                    raise ValueError('Restored parallel part has no exact footprint identity.')
                configured={'footprint_uuid':owner,'from_pad':left['id'],'to_pad':right['id'],
                            'model':model(part)}
                for key in ('from_pads','to_pads'):
                    if key in part:configured[key]=deepcopy(part[key])
                parallel.append(configured)
            branch['parallel']=parallel
        branches.append(branch)
    path={'schema':1,'source':token(request.get('source_terminal')),
          'sink':token(request.get('sink_terminal')),'branches':branches}
    for key in ('source_terminals','sink_terminals'):
        if key in request:path[key]=deepcopy(request[key])
    parse_saved_path(path,inventory)
    return {'path':path,'editor':{}}


def reviewed_pair(inventory, net, from_pad, to_pad):
    """One explicit current path; unrelated component pads remain untouched."""
    def resolve(value):
        rows = [row for row in inventory.get('terminals', []) if value in (row['id'], row.get('label'))]
        if len(rows) != 1:
            raise ValueError('Choose one unambiguous saved pad at each end of the component.')
        return rows[0]
    entry, exit_pad = resolve(from_pad), resolve(to_pad)
    reference = entry.get('reference', entry['label'].rsplit('.', 1)[0])
    other = exit_pad.get('reference', exit_pad['label'].rsplit('.', 1)[0])
    if reference != other or (entry.get('footprint_uuid') and exit_pad.get('footprint_uuid') and
                              entry['footprint_uuid'] != exit_pad['footprint_uuid']):
        raise ValueError('Both current terminals must belong to the same component.')
    if entry['id'] == exit_pad['id'] or entry.get('net') != net or not exit_pad.get('net') or exit_pad['net'] == net:
        raise ValueError('Choose distinct current terminals from the current net to a different assigned net.')
    return reference, entry, exit_pad


def parse_saved_path(data, inventory):
    """Shared GUI/CLI path intake; explicit groups survive the console grammar."""
    from .console import parse_command
    from .parallel_parts import with_parallel, reviewed_group
    if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('branches'),list) or len(data['branches'])>128:
        raise ValueError('Unsupported or oversized series-path file.')
    if set(data)-{'schema','source','sink','branches','source_terminals','sink_terminals'}:
        raise ValueError('Unsupported series-path fields.')
    if any(not isinstance(data.get(key),str) or not data[key].strip() for key in ('source','sink')):
        raise ValueError('Series-path source and sink must be explicit pad labels or UUIDs.')
    for branch in data['branches']:
        if not isinstance(branch,dict) or any(not isinstance(branch.get(key),str) or not branch[key].strip() for key in ('reference','model')):
            raise ValueError('Each series row needs an explicit component reference and model.')
        if any(key in branch and (not isinstance(branch[key],str) or not branch[key]) for key in ('from_pad','to_pad')):
            raise ValueError('Explicit series pad anchors must be labels or UUIDs.')
    parsed=with_parallel(parse_command(build_command(data['source'],data['sink'],data['branches']),inventory),data['branches'],inventory)
    for key,anchor in (('source_terminals','source_terminal'),('sink_terminals','sink_terminal')):
        if key in data:parsed[key]=reviewed_group(inventory,parsed[anchor],data[key])
    occupied=set()
    def reserve(anchor, names=None):
        ids=reviewed_group(inventory,anchor,names)
        if occupied.intersection(ids):raise ValueError('Repeated series endpoint across source, sink or component electrodes.')
        occupied.update(ids)
    reserve(parsed['source_terminal'],parsed.get('source_terminals'))
    reserve(parsed['sink_terminal'],parsed.get('sink_terminals'))
    for stage in parsed['series']:
        for branch in [stage,*stage.get('parallel',[])]:
            reserve(branch['from_pad'],branch.get('from_pads'));reserve(branch['to_pad'],branch.get('to_pads'))
    return parsed


def _editor_selection(board_path):
    """Read selection only from the KiCad editor that launched this window."""
    from wayricad_runtime.context import connect, saved_board
    client = connect()
    if saved_board(client) != Path(board_path).resolve():
        raise ValueError('The originating PCB Editor changed boards. Reopen Quick PI.')
    return client.get_board().get_selection()


def selected_pad_labels(board_path, inventory):
    selected=set(selected_pad_ids(board_path,inventory))
    return [row['label'] for row in inventory.get('terminals',[]) if row['id'] in selected]


def selected_pad_ids(board_path, inventory):
    from wayricad_runtime.ipc import uid
    selected = {uid(item) for item in _editor_selection(board_path)}
    return [row['id'] for row in inventory.get('terminals', []) if row['id'] in selected]


def selected_component_references(board_path):
    """Return references of selected footprint instances, leaving models explicit."""
    result = []
    for item in _editor_selection(board_path):
        field = getattr(item, 'reference_field', None)
        reference = getattr(getattr(field, 'text', None), 'value', None)
        if reference:
            result.append(str(reference))
    return sorted(set(result))


def rl_model(resistance, inductance):
    """Each dedicated field is one quantity; inductance always carries H."""
    from .console import _VALUE, _rl
    resistance, inductance = resistance.strip(), inductance.strip()
    for text, is_inductance in ((resistance, False), (inductance, True)):
        if not text:
            continue
        match = _VALUE.fullmatch(text)
        if not match or (match.group(3) == 'H') != is_inductance:
            raise ValueError('Enter one quantity per field. Inductance requires an explicit H unit '
                             '(e.g. 1mH, 10nH or 1pH); resistance uses ohms (e.g. 5mΩ). '
                             'Expressions such as 1m+1p are ambiguous.')
    model = '+'.join(value for value in (resistance, inductance) if value)
    _rl(model)
    return model


class SeriesPathDialog:
    def __init__(self, parent, inventory, board_path, existing=None):
        import wx
        from wayricad_runtime.readable_choice import ReadableChoice
        self.wx = wx;self.inventory=inventory;self.board_path=board_path;self.request=None
        initial_path=existing.get('path',{}) if isinstance(existing,dict) and 'path' in existing else existing
        self.branches=deepcopy(initial_path.get('branches',[])) if isinstance(initial_path,dict) else []
        self.endpoint_groups={}
        self.dialog=wx.Dialog(parent,title='Quick PI · Series path editor',
                              size=parent.FromDIP((930,700)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        body=wx.ScrolledWindow(self.dialog,style=wx.VSCROLL|wx.HSCROLL)
        self.body=body;body.SetScrollRate(12,12);body.SetMinSize((0,0))
        root=wx.BoxSizer(wx.VERTICAL)
        intro=wx.StaticText(body,label='Choose source and sink pads, then add components in path order. For multi-pad devices, review an explicit current-terminal pair. Values are explicit assumptions; saved copper supplies the intervening nets.')
        intro.Wrap(parent.FromDIP(880));root.Add(intro,0,wx.EXPAND|wx.ALL,12)
        from .console import terminal_aliases
        self._pad_aliases=terminal_aliases(inventory)
        by_id={str(row['id']):row for row in inventory.get('terminals',[])}
        self._display_to_token={alias:(identifier if alias!=by_id[identifier]['label'] else alias)
            for identifier,alias in self._pad_aliases.items()}
        labels=sorted(self._display_to_token)
        endpoints=wx.BoxSizer(wx.HORIZONTAL)
        self.source=ReadableChoice(body,choices=labels);self.sink=ReadableChoice(body,choices=labels)
        if labels:self.source.SetSelection(0);self.sink.SetSelection(min(1,len(labels)-1))
        for name,ctrl in (('Source pad',self.source),('Sink pad',self.sink)):
            endpoints.Add(wx.StaticText(body,label=name),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
            endpoints.Add(ctrl,1,wx.RIGHT,12)
        select=wx.Button(body,label='Use KiCad selected pads');endpoints.Add(select,0)
        select.Bind(wx.EVT_BUTTON,self._selection)
        root.Add(endpoints,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        peer_row=wx.BoxSizer(wx.HORIZONTAL)
        self.source_all=wx.CheckBox(body,label='Include all same-component/net source pads')
        self.sink_all=wx.CheckBox(body,label='Include all same-component/net sink pads (total current)')
        for control in (self.source_all,self.sink_all):
            peer_row.Add(control,1,wx.RIGHT,10);control.Bind(wx.EVT_CHECKBOX,self._changed)
        root.Add(peer_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        infer_row=wx.WrapSizer(wx.HORIZONTAL)
        infer=wx.Button(body,label='Infer paths from source to sink…')
        infer.Bind(wx.EVT_BUTTON,self._infer)
        infer_row.Add(infer,0,wx.RIGHT,10)
        self.infer_unknown=wx.CheckBox(body,label='Include other device types (review current pins and device state)')
        infer_row.Add(self.infer_unknown,0,wx.ALIGN_CENTER_VERTICAL)
        root.Add(infer_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        main=wx.BoxSizer(wx.HORIZONTAL)
        left=wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(body,label='Ordered component path'),0,wx.BOTTOM,5)
        self.list=wx.ListBox(body);left.Add(self.list,1,wx.EXPAND)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        for title,handler in (('Remove',self._remove),('Move up',self._up),('Move down',self._down)):
            button=wx.Button(body,label=title);button.Bind(wx.EVT_BUTTON,handler);actions.Add(button,0,wx.RIGHT,5)
        left.Add(actions,0,wx.TOP,7);main.Add(left,1,wx.EXPAND|wx.RIGHT,14)
        self.parallel_button=wx.Button(body,label='Parallel parts…')
        self.parallel_button.Bind(wx.EVT_BUTTON,self._parallel)
        left.Add(self.parallel_button,0,wx.EXPAND|wx.TOP,7)
        self.list.Bind(wx.EVT_LISTBOX,self._parallel_note)
        right=wx.BoxSizer(wx.VERTICAL)
        right.Add(wx.StaticText(body,label='Add next component'),0,wx.BOTTOM,5)
        self.component=ReadableChoice(body);right.Add(self.component,0,wx.EXPAND|wx.BOTTOM,10)
        self.kind=ReadableChoice(body,choices=['Resistance / RL','Fixed forward drop','Diode at DC current'])
        self.kind.SetSelection(0);right.Add(self.kind,0,wx.EXPAND|wx.BOTTOM,10)
        self.values={};grid=wx.FlexGridSizer(0,2,6,9);grid.AddGrowableCol(1,1)
        for key,title,initial in (('r','Resistance (e.g. 5mΩ)','5m'),('l','Inductance (H required)',''),
                                  ('fixed','Fixed forward drop','1V'),('vf','Vf at Iref','0.7V'),
                                  ('iref','Reference current','1A'),('n','Ideality n','2'),('t','Junction temperature','25C')):
            label=wx.StaticText(body,label=title);control=wx.TextCtrl(body,value=initial)
            grid.Add(label,0,wx.ALIGN_CENTER_VERTICAL);grid.Add(control,1,wx.EXPAND)
            self.values[key]=(label,control)
            if key=='r':control.SetHint('5mΩ or 0.1Ω; one resistance')
            if key=='l':control.SetHint('1mH, 10nH or 1pH; blank omits L')
        right.Add(grid,0,wx.EXPAND|wx.BOTTOM,8)
        add_actions=wx.BoxSizer(wx.HORIZONTAL)
        selected_component=wx.Button(body,label='Use selected component')
        selected_component.Bind(wx.EVT_BUTTON,self._selected_component)
        add_actions.Add(selected_component,0,wx.RIGHT,8)
        add=wx.Button(body,label='Add component to path');add.Bind(wx.EVT_BUTTON,self._add)
        add_actions.Add(add,0);right.Add(add_actions,0,wx.ALIGN_RIGHT)
        explicit=wx.Button(body,label='Add explicit pad pair…')
        explicit.Bind(wx.EVT_BUTTON,self._explicit_pair)
        right.Add(explicit,0,wx.ALIGN_RIGHT|wx.TOP,8);main.Add(right,1,wx.EXPAND)
        root.Add(main,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        root.Add(wx.StaticText(body,label='Manual saved-net path · type or paste, then apply'),0,wx.LEFT|wx.TOP,12)
        self.manual=wx.TextCtrl(body)
        self.manual.SetHint('run pi J1.1 Q1.1 100m Q1.3 U1.1')
        root.Add(self.manual,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        self.manual_matches=wx.ListBox(body,size=(-1,72))
        root.Add(self.manual_matches,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,12)
        apply_manual=wx.Button(body,label='Use manual path')
        apply_manual.Bind(wx.EVT_BUTTON,self._apply_manual)
        root.Add(apply_manual,0,wx.ALIGN_RIGHT|wx.RIGHT|wx.TOP,12)
        self.manual.Bind(wx.EVT_TEXT,self._manual_changed)
        self.manual_matches.Bind(wx.EVT_LISTBOX_DCLICK,self._manual_pick)
        self._manual_pending=False
        root.Add(wx.StaticText(body,label='Preview and validation'),0,wx.LEFT|wx.TOP,12)
        self.preview=wx.TextCtrl(body,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,100))
        root.Add(self.preview,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        body.SetSizer(root)
        outer=wx.BoxSizer(wx.VERTICAL);outer.Add(body,1,wx.EXPAND)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        save=wx.Button(self.dialog,label='Save path…');load=wx.Button(self.dialog,label='Load path…')
        save.Bind(wx.EVT_BUTTON,self._save);load.Bind(wx.EVT_BUTTON,self._load)
        footer.Add(load,0,wx.RIGHT,7);footer.Add(save,0,wx.RIGHT,7)
        tree=wx.Button(self.dialog,label='Power tree…')
        tree.Bind(wx.EVT_BUTTON,self._power_tree);footer.Add(tree,0)
        footer.AddStretchSpacer()
        run=wx.Button(self.dialog,wx.ID_OK,label='Run this path');cancel=wx.Button(self.dialog,wx.ID_CANCEL,label='Cancel')
        run.Bind(wx.EVT_BUTTON,self._run);footer.Add(run,0,wx.RIGHT,8);footer.Add(cancel,0)
        outer.Add(footer,0,wx.EXPAND|wx.ALL,12)
        self.dialog.SetSizer(outer)
        display=wx.Display.GetFromWindow(parent)
        work=wx.Display(max(0,display)).GetClientArea()
        desired=parent.FromDIP((930,700));margin=parent.FromDIP(16)
        width=min(desired.width,max(1,work.width-2*margin))
        height=min(desired.height,max(1,work.height-2*margin))
        self.dialog.SetSize((width,height))
        self.dialog.SetPosition((work.x+(work.width-width)//2,work.y+(work.height-height)//2))
        self.source.Bind(wx.EVT_CHOICE,self._changed);self.sink.Bind(wx.EVT_CHOICE,self._changed)
        self.kind.Bind(wx.EVT_CHOICE,self._changed)
        self._changed()
        if isinstance(initial_path,dict):
            self._restore_path(initial_path)
        else:
            from .pin_units import peers
            for control,check in ((self.source,self.source_all),(self.sink,self.sink_all)):
                value=self._chosen(control)
                matches=[row for row in self.inventory.get('terminals',[])
                         if value in (row.get('id'),row.get('label'))]
                check.SetValue(len(matches)==1 and bool(peers(self.inventory['terminals'],matches[0]['id'])))
            self._changed()
        if isinstance(existing,dict) and isinstance(existing.get('editor'),dict):
            editor=existing['editor']
            kind=editor.get('kind')
            if type(kind) is int and 0<=kind<self.kind.GetCount():self.kind.SetSelection(kind)
            for key,value in editor.get('values',{}).items():
                if key in self.values and isinstance(value,str):self.values[key][1].SetValue(value)
            self._changed()
            component=editor.get('component')
            choice=next((i for i,(reference,_) in enumerate(self.candidates) if reference==component),None)
            if choice is not None:self.component.SetSelection(choice)
            selected=editor.get('selected_stage')
            if type(selected) is int and 0<=selected<len(self.branches):self.list.SetSelection(selected)
            self.manual.SetValue(editor.get('manual','') if isinstance(editor.get('manual'),str) else '')
            self._manual_pending=bool(editor.get('manual_pending'))

    def _restore_path(self,data):
        """Restore saved schema-1 controls without replacing exact pad identities."""
        for control,key in ((self.source,'source'),(self.sink,'sink')):
            value=data.get(key)
            matches=[row for row in self.inventory.get('terminals',[])
                     if value in (row.get('id'),row.get('label'),self._pad_aliases.get(str(row.get('id'))))]
            if len(matches)==1:control.SetStringSelection(self._pad_aliases[str(matches[0]['id'])])
            else:control.SetSelection(self.wx.NOT_FOUND)
        self.source_all.SetValue(len(data.get('source_terminals',[]))>1)
        self.sink_all.SetValue(len(data.get('sink_terminals',[]))>1)
        self.endpoint_groups={key:deepcopy(data[key]) for key in ('source_terminals','sink_terminals')
                              if isinstance(data.get(key),list)}
        self.branches=deepcopy(data.get('branches',[]))
        self._changed()

    def _power_tree(self,event=None):
        from .series_power_tree import series_path_tree
        from .series_power_tree_ui import show_series_power_tree
        try:
            tree=series_path_tree(self._path_data(),self.inventory)
            if tree is None:raise ValueError('Infer or enter a series path first.')
            show_series_power_tree(self.dialog,tree)
        except (ValueError,KeyError) as exc:
            self.wx.MessageBox(str(exc),'Series power tree',self.wx.OK|self.wx.ICON_INFORMATION,self.dialog)

    def _infer(self,event=None):
        from .series_inference import choose_inferred_path
        try:
            data=choose_inferred_path(self.dialog,self.inventory,self._chosen(self.source),self._chosen(self.sink),
                                      include_unknown=self.infer_unknown.GetValue())
            if data is not None:
                self._restore_path(data)
                self.manual.SetValue('');self._manual_pending=False
        except ValueError as exc:
            self.wx.MessageBox(str(exc),'Infer series paths',self.wx.OK|self.wx.ICON_WARNING,parent=self.dialog)

    def draft_snapshot(self):
        """Capture even an unfinished dialog; callers retain this until PI closes."""
        try:path=deepcopy(self._path_data())
        except ValueError:
            path={'schema':1,'source':self._chosen(self.source),'sink':self._chosen(self.sink),
                  'branches':deepcopy(self.branches),**deepcopy(self.endpoint_groups)}
        selected=self.component.GetSelection()
        component=self.candidates[selected][0] if 0<=selected<len(self.candidates) else None
        return {'path':path,'editor':{'kind':self.kind.GetSelection(),
            'values':{key:control.GetValue() for key,(_,control) in self.values.items()},
            'component':component,'selected_stage':self.list.GetSelection(),
            'manual':self.manual.GetValue(),'manual_pending':self._manual_pending}}

    def _manual_changed(self,event):
        from .console import suggestions
        self._manual_pending=True
        self.manual_matches.Set(suggestions(self.manual.GetValue(),self.inventory)[:12])
        event.Skip()

    def _manual_pick(self,event):
        choice=self.manual_matches.GetStringSelection()
        if choice:self.manual.SetValue(choice);self.manual.SetInsertionPointEnd();self.manual.SetFocus()
        event.Skip()

    def _apply_manual(self,event):
        try:
            try:previous=self._path_data()
            except ValueError:previous={}
            data=path_from_command(self.manual.GetValue(),self.inventory,existing=previous)
            self._restore_path(data)
            self._manual_pending=False
            return True
        except ValueError as exc:
            self.wx.MessageBox(str(exc),'Review manual series path',self.wx.OK|self.wx.ICON_WARNING)
            return False

    def _parallel_candidates(self,index):
        from .parallel_parts import stage_pads,candidates
        start,end=stage_pads(self.inventory,self._chosen(self.source),self.branches,index)
        excluded={part['footprint_uuid'] for i,branch in enumerate(self.branches) if i!=index
                  for part in branch.get('parallel',[])}
        primary_refs={branch['reference'] for branch in self.branches}
        excluded.update(row['footprint_uuid'] for row in self.inventory.get('terminals',[])
                        if row.get('footprint_uuid') and row.get('reference',row.get('label','').rsplit('.',1)[0]) in primary_refs)
        return candidates(self.inventory,start,end,excluded)

    def _parallel_note(self,event=None):
        try:count=len(self._parallel_candidates(self.list.GetSelection()))
        except (ValueError,KeyError):count=0
        self.parallel_button.SetLabel(f'Parallel parts ({count})…');self.parallel_button.Enable(count>0)
        if event:event.Skip()

    def _path_data(self):
        from .pin_units import peers
        data={'schema':1,'source':self._chosen(self.source),'sink':self._chosen(self.sink),'branches':self.branches}
        for control,check,key in ((self.source,self.source_all,'source_terminals'),(self.sink,self.sink_all,'sink_terminals')):
            if not check.GetValue():continue
            selected=[row for row in self.inventory.get('terminals',[])
                      if self._chosen(control) in (row.get('id'),row.get('label'))]
            if len(selected)!=1:raise ValueError('Choose an unambiguous source and sink anchor.')
            identifier=selected[0]['id']
            if key in self.endpoint_groups:
                data[key]=list(self.endpoint_groups[key])
            else:data[key]=[identifier,*[row['id'] for row in peers(self.inventory['terminals'],identifier)]]
        return data

    def _parsed(self):
        return parse_saved_path(self._path_data(),self.inventory)

    def _parallel(self,event):
        from .parallel_parts import suggested_resistance
        from .console import _model
        wx=self.wx;index=self.list.GetSelection()
        try:parts=self._parallel_candidates(index)
        except (ValueError,KeyError) as exc:self.preview.SetValue(str(exc));return
        dialog=wx.Dialog(self.dialog,title='Review parallel components',size=(780,560),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='These parts have current pads on the exact saved net pair. Check each part and its incoming/outgoing pads, then review the R/L model. Gate, control and other-net pads stay excluded. Capacitor, diode and unknown DCR models are not guessed.')
        note.Wrap(720);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        area=wx.ScrolledWindow(dialog,style=wx.VSCROLL);area.SetScrollRate(0,12);stack=wx.BoxSizer(wx.VERTICAL)
        selected={row['footprint_uuid']:row for row in self.branches[index].get('parallel',[])}
        controls=[]
        for part in parts:
            old=selected.get(part['footprint_uuid'],{})
            pad_labels=self._pad_aliases
            panel=wx.Panel(area);item=wx.BoxSizer(wx.VERTICAL)
            check=wx.CheckBox(panel,label=part['id']+' · '+str(part['component_value']))
            item.Add(check,0,wx.BOTTOM,4)
            check.SetValue(bool(old))
            for title,key,anchor in (('Incoming current pads','from_pads','from_pad'),
                                     ('Outgoing current pads','to_pads','to_pad')):
                item.Add(wx.StaticText(panel,label=title),0,wx.TOP|wx.BOTTOM,3)
                chosen=set(old.get(key,[old.get(anchor,part[anchor])]) if old else part[key])
                checks=[];line=wx.BoxSizer(wx.HORIZONTAL)
                for identifier in part[key]:
                    pad=wx.CheckBox(panel,label=pad_labels.get(identifier,identifier))
                    pad.SetValue(identifier in chosen);line.Add(pad,0,wx.RIGHT,10)
                    checks.append((identifier,pad))
                item.Add(line,0,wx.EXPAND)
                if key=='from_pads':incoming_checks=checks
                else:outgoing_checks=checks
            if part['excluded_pads']:
                item.Add(wx.StaticText(panel,label='Excluded other-net pads: '+
                         ', '.join(pad_labels.get(value,value) for value in part['excluded_pads'])),0,wx.TOP,4)
            item.Add(wx.StaticText(panel,label='Reviewed R/L model'),0,wx.TOP,5)
            model=wx.TextCtrl(panel,value=old.get('model',suggested_resistance(part)))
            model.SetHint('Explicit model, e.g. 100m or 10mH+30m')
            item.Add(model,0,wx.EXPAND|wx.BOTTOM,5)
            panel.SetSizer(item);stack.Add(panel,0,wx.EXPAND|wx.ALL,8)
            controls.append((part,check,model,incoming_checks,outgoing_checks))
        area.SetSizer(stack);layout.Add(area,1,wx.EXPAND|wx.ALL,10)
        highlight=wx.Button(dialog,label='Highlight detected parts on PCB')
        def locate(_event):
            try:
                from .origin_selection import select_origin
                select_origin(self.board_path,[part['footprint_uuid'] for part in parts])
            except Exception as exc:note.SetLabel('Highlight unavailable: '+str(exc));note.Wrap(630);dialog.Layout()
        highlight.Bind(wx.EVT_BUTTON,locate);layout.Add(highlight,0,wx.ALL,10)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,10);dialog.SetSizer(layout)
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            reviewed=[]
            for part,check,text,incoming_checks,outgoing_checks in controls:
                if not check.GetValue():continue
                model=text.GetValue().strip();parsed=_model(model)
                if 'diode' in parsed or 'fixed_drop_v' in parsed:raise ValueError('Parallel DC stages require R/L models.')
                incoming=[identifier for identifier,control in incoming_checks if control.GetValue()]
                outgoing=[identifier for identifier,control in outgoing_checks if control.GetValue()]
                if not incoming or not outgoing:raise ValueError('Choose at least one incoming and outgoing current pad for each selected parallel part.')
                reviewed.append({'footprint_uuid':part['footprint_uuid'],'from_pad':incoming[0],
                                 'to_pad':outgoing[0],'from_pads':incoming,'to_pads':outgoing,'model':model})
            self.branches[index]['parallel']=reviewed;self._changed();self.list.SetSelection(index);self._parallel_note()
        except ValueError as exc:wx.MessageBox(str(exc),'Review parallel models',wx.OK|wx.ICON_WARNING)
        finally:dialog.Destroy()

    def _chosen(self,control):
        if control.GetSelection()<0:return ''
        selection=control.GetStringSelection()
        return self._display_to_token.get(selection,selection) if control in (self.source,self.sink) and hasattr(self,'_display_to_token') else selection

    def _cursor_net(self):
        label=self._chosen(self.source)
        row=next((row for row in self.inventory.get('terminals',[]) if label in (row['id'],row.get('label'))),None)
        if row is None:return ''
        net=row['net']
        for branch in self.branches:
            if 'from_pad' in branch or 'to_pad' in branch:
                try:
                    reference,entry,exit_pad=reviewed_pair(self.inventory,net,branch.get('from_pad'),branch.get('to_pad'))
                    if reference!=branch['reference']:return ''
                    net=exit_pad['net']
                except ValueError:return ''
            else:
                choice=next((other for ref,other in compatible_components(self.inventory,net)
                             if ref==branch['reference']),None)
                if choice is None:return ''
                net=choice
        return net

    def _changed(self,event=None):
        wx=self.wx
        from .pin_units import peers
        changed=event.GetEventObject() if event and hasattr(event,'GetEventObject') else None
        for control,check,role in ((self.source,self.source_all,'source'),(self.sink,self.sink_all,'sink')):
            if changed is control or changed is check:self.endpoint_groups.pop(role+'_terminals',None)
            if changed is control:check.SetValue(False)
            selected=next((row for row in self.inventory.get('terminals',[]) if self._chosen(control) in (row.get('id'),row.get('label'))),None)
            others=peers(self.inventory.get('terminals',[]),selected['id']) if selected else []
            check.Enable(bool(others))
            if not others:check.SetValue(False)
            elif changed is control:check.SetValue(True)
            check.SetLabel('Include all '+str(len(others)+1)+' same-component/net '+role+' pads'+(' (total current)' if role=='sink' else ''))
        active=self.kind.GetSelection()
        for key,(label,control) in self.values.items():
            show=key in (('r','l') if active==0 else ('fixed',) if active==1 else ('vf','iref','n','t'))
            label.Show(show);control.Show(show)
        self.dialog.Layout()
        body=getattr(self,'body',None)
        if body is not None:body.Layout();body.FitInside()
        net=self._cursor_net();used={item['reference'] for item in self.branches}
        self.candidates=compatible_components(self.inventory,net,used) if net else []
        self.component.Set([ref+' · '+net+' → '+next_net for ref,next_net in self.candidates])
        if self.candidates:self.component.SetSelection(0)
        pad_labels=self._pad_aliases
        self.list.Set([row['reference']+'  ·  '+(pad_labels.get(row['from_pad'],row['from_pad'])+' → '+pad_labels.get(row['to_pad'],row['to_pad'])+'  ·  ' if 'from_pad' in row else '')+row['model']+(f" (+{len(row['parallel'])} parallel)" if row.get('parallel') else '') for row in self.branches])
        if self.branches:self.list.SetSelection(len(self.branches)-1)
        self._parallel_note()
        try:
            command=display_path_command(self._path_data(),self.inventory)
            parsed=self._parsed()
            found=[part['id'] for i in range(len(self.branches)) for part in self._parallel_candidates(i)]
            groups=grouped_pad_preview(parsed,self.inventory)
            self.preview.SetValue(command+'\n\nValid saved-net path · '+str(len(parsed['series']))+' series stage(s).'+
                                  ('\n'+'\n'.join(groups) if groups else '')+
                                  ('\nDetected parallel parts: '+', '.join(found)+' · review with Parallel parts.' if found else ''))
        except Exception as exc:
            self.preview.SetValue((command if 'command' in locals() else '')+'\n\nReview: '+str(exc))
        if event:event.Skip()

    def _model(self):
        def value(key):return self.values[key][1].GetValue().strip()
        kind=self.kind.GetSelection()
        if kind==0:
            return rl_model(value('r'),value('l'))
        if kind==1:return value('fixed')
        return f"diode(Vf={value('vf')},Iref={value('iref')},n={value('n')},T={value('t')})"

    def _add(self,event):
        if self.component.GetSelection()<0:return
        reference=self.candidates[self.component.GetSelection()][0]
        from .console import _model
        try:
            model=self._model()
            _model(model)
        except ValueError as exc:self.wx.MessageBox(str(exc),'Invalid component model',self.wx.OK|self.wx.ICON_WARNING);return
        self.branches.append({'reference':reference,'model':model});self._changed()

    def _explicit_pair(self,event):
        from wayricad_runtime.readable_choice import ReadableChoice
        wx=self.wx;net=self._cursor_net()
        rows=self.inventory.get('terminals',[]);used={branch['reference'] for branch in self.branches}
        grouped={}
        for row in rows:
            reference=row.get('reference',row['label'].rsplit('.',1)[0])
            if reference not in used:grouped.setdefault(reference,[]).append(row)
        eligible={ref:pads for ref,pads in sorted(grouped.items())
                  if any(p.get('net')==net for p in pads) and any(p.get('net') and p['net']!=net for p in pads)}
        if not net or not eligible:
            wx.MessageBox('No unused component has assigned current terminals across the next net transition.',
                          'Explicit current terminals',wx.OK|wx.ICON_WARNING);return
        dialog=wx.Dialog(self.dialog,title='Review explicit component current terminals',size=(750,510),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='Choose exactly one incoming and one outgoing saved pad. The explicit model is taken from the series editor. Other pads, including gate/control pins, are not modeled or shorted. Device bias and operating state require your review; this does not simulate a switch or controller.')
        note.Wrap(650);layout.Add(note,0,wx.EXPAND|wx.ALL,12)
        component=ReadableChoice(dialog,choices=list(eligible));component.SetSelection(0)
        entry=ReadableChoice(dialog);exit_pad=ReadableChoice(dialog)
        for label,control in (('Component',component),('Incoming current pad',entry),('Outgoing current pad',exit_pad)):
            layout.Add(wx.StaticText(dialog,label=label),0,wx.LEFT|wx.RIGHT|wx.TOP,12)
            layout.Add(control,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        include_in=wx.CheckBox(dialog,label='Include all other same-net incoming pads on this component')
        include_out=wx.CheckBox(dialog,label='Include all other same-net outgoing pads on this component')
        layout.Add(include_in,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,12)
        layout.Add(include_out,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        group_preview=wx.StaticText(dialog,label='')
        layout.Add(group_preview,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,12)
        incoming=[];outgoing=[]
        from .pin_units import peers
        def show_groups(_event=None):
            def labels(pads,choice,check):
                if not pads or choice.GetSelection()<0:return 'None'
                ids=current_pad_group(rows,pads[choice.GetSelection()]['id'],check.GetValue())
                return ', '.join(self._pad_aliases.get(str(value),str(value)) for value in ids)
            group_preview.SetLabel('Incoming: '+labels(incoming,entry,include_in)+
                                   '\nOutgoing: '+labels(outgoing,exit_pad,include_out))
            group_preview.Wrap(700);dialog.Layout()
        def default_group(check,pads,choice):
            check.SetValue(bool(pads) and choice.GetSelection()>=0 and
                           bool(peers(rows,pads[choice.GetSelection()]['id'])))
            show_groups()
        def update(_event=None):
            incoming[:]=[p for p in eligible[component.GetStringSelection()] if p.get('net')==net]
            outgoing[:]=[p for p in eligible[component.GetStringSelection()] if p.get('net') and p['net']!=net]
            for control,pads in ((entry,incoming),(exit_pad,outgoing)):
                control.Set([self._pad_aliases.get(str(p['id']),p['label'])+' ['+p['net']+']' for p in pads]);control.SetSelection(0)
            default_group(include_in,incoming,entry);default_group(include_out,outgoing,exit_pad)
        component.Bind(wx.EVT_CHOICE,update);update()
        entry.Bind(wx.EVT_CHOICE,lambda _event:default_group(include_in,incoming,entry))
        exit_pad.Bind(wx.EVT_CHOICE,lambda _event:default_group(include_out,outgoing,exit_pad))
        include_in.Bind(wx.EVT_CHECKBOX,show_groups);include_out.Bind(wx.EVT_CHECKBOX,show_groups)
        reviewed=wx.CheckBox(dialog,label='I reviewed these current terminals and the explicit model; other pads remain excluded.')
        layout.Add(reviewed,0,wx.EXPAND|wx.ALL,12)
        layout.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,12);dialog.SetSizer(layout)
        try:
            if dialog.ShowModal()!=wx.ID_OK:return
            if not reviewed.GetValue():raise ValueError('Review the current-terminal pair and explicit model before adding it.')
            reference,a,b=reviewed_pair(self.inventory,net,incoming[entry.GetSelection()]['id'],outgoing[exit_pad.GetSelection()]['id'])
            model=self._model()
            from .console import _model
            _model(model)
            branch={'reference':reference,'from_pad':a['id'],'to_pad':b['id'],'model':model}
            for row,check,key in ((a,include_in,'from_pads'),(b,include_out,'to_pads')):
                if check.GetValue():branch[key]=current_pad_group(rows,row['id'],True)
            self.branches.append(branch)
            self._changed()
        except (ValueError,IndexError) as exc:
            wx.MessageBox(str(exc),'Review explicit current terminals',wx.OK|wx.ICON_WARNING)
        finally:dialog.Destroy()

    def _selected_component(self,event):
        try:
            selected=selected_component_references(self.board_path)
            matches=[i for i,(ref,_) in enumerate(self.candidates) if ref in selected]
            if len(matches)!=1:
                raise ValueError('Select exactly one compatible two-pad component at the next net transition in the originating PCB Editor.')
            self.component.SetSelection(matches[0])
            self._add(event)
        except Exception as exc:
            self.wx.MessageBox(str(exc),'KiCad component selection',self.wx.OK|self.wx.ICON_WARNING)

    def _remove(self,event):
        index=self.list.GetSelection()
        if index>=0:self.branches.pop(index);self._changed()

    def _up(self,event):
        index=self.list.GetSelection()
        if index>0:self.branches[index-1],self.branches[index]=self.branches[index],self.branches[index-1];self._changed();self.list.SetSelection(index-1)

    def _down(self,event):
        index=self.list.GetSelection()
        if 0<=index<len(self.branches)-1:self.branches[index+1],self.branches[index]=self.branches[index],self.branches[index+1];self._changed();self.list.SetSelection(index+1)

    def _selection(self,event):
        try:
            identifiers=selected_pad_ids(self.board_path,self.inventory)
            if not identifiers:raise ValueError('Select one or two saved-board pads in the originating PCB Editor, then retry.')
            self.source_all.SetValue(False);self.sink_all.SetValue(False);self.endpoint_groups.clear()
            for control,identifier in ((self.source,identifiers[0]),(self.sink,identifiers[1] if len(identifiers)>1 else '')):
                if identifier:control.SetStringSelection(self._pad_aliases[str(identifier)])
            self._changed()
            if len(identifiers)>2:self.wx.MessageBox('More than two pads are selected. The first two were used; review their order.','Selection review')
        except Exception as exc:self.wx.MessageBox(str(exc),'KiCad selection',self.wx.OK|self.wx.ICON_WARNING)

    def _save(self,event):
        if self._manual_pending and not self._apply_manual(event):return
        try:
            data=self._path_data()
            parse_saved_path(data,self.inventory)
        except ValueError as exc:
            self.wx.MessageBox(str(exc),'Complete the series path before saving',self.wx.OK|self.wx.ICON_WARNING)
            return
        with self.wx.FileDialog(self.dialog,'Save series path',defaultDir=str(Path(self.board_path).parent),
             wildcard='JSON (*.json)|*.json',style=self.wx.FD_SAVE|self.wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=self.wx.ID_OK:return
            target=Path(dialog.GetPath());board=Path(self.board_path)
            if (target.suffix.lower()!='.json' or target.resolve()==board.resolve()
                    or target.exists() and board.exists() and target.samefile(board)):
                self.wx.MessageBox('Choose a .json series path file distinct from the PCB.',
                                   'Cannot save path',self.wx.OK|self.wx.ICON_WARNING)
                return
            target.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')

    def _load(self,event):
        with self.wx.FileDialog(self.dialog,'Load series path',defaultDir=str(Path(self.board_path).parent),
             wildcard='JSON (*.json)|*.json',style=self.wx.FD_OPEN|self.wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=self.wx.ID_OK:return
            try:
                data=json.loads(Path(dialog.GetPath()).read_text(encoding='utf-8'))
                parse_saved_path(data,self.inventory)
                self._restore_path(data)
                self.manual.SetValue('');self._manual_pending=False
            except (OSError,KeyError,TypeError,ValueError) as exc:
                self.wx.MessageBox(str(exc),'Cannot load path',self.wx.OK|self.wx.ICON_WARNING)

    def _run(self,event):
        try:
            if self._manual_pending and not self._apply_manual(event):return
            self.request=self._parsed()
            self.dialog.EndModal(self.wx.ID_OK)
        except ValueError as exc:self.wx.MessageBox(str(exc),'Review the series path',self.wx.OK|self.wx.ICON_WARNING)

    def show_with_draft(self):
        """Return request and in-memory draft on Run, Cancel, or window close."""
        try:
            accepted=self.dialog.ShowModal()==self.wx.ID_OK
            return (self.request if accepted else None),self.draft_snapshot()
        finally:self.dialog.Destroy()

    def show(self):
        return self.show_with_draft()[0]
