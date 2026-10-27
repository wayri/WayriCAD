"""Native series-path editor backed by the same bounded Quick PI parser."""
from __future__ import annotations

import json
from pathlib import Path
import shlex


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
        tokens.append(branch['reference'] + ':' + branch['model'])
    tokens.append(sink_label)
    return shlex.join(tokens)


def _editor_selection(board_path):
    """Read selection only from the KiCad editor that launched this window."""
    from wayricad_runtime.context import connect, saved_board
    client = connect()
    if saved_board(client) != Path(board_path).resolve():
        raise ValueError('The originating PCB Editor changed boards. Reopen Quick PI.')
    return client.get_board().get_selection()


def selected_pad_labels(board_path, inventory):
    from wayricad_runtime.ipc import uid
    selected = {uid(item) for item in _editor_selection(board_path)}
    return [row['label'] for row in inventory.get('terminals', []) if row['id'] in selected]


def selected_component_references(board_path):
    """Return references of selected footprint instances, leaving models explicit."""
    result = []
    for item in _editor_selection(board_path):
        field = getattr(item, 'reference_field', None)
        reference = getattr(getattr(field, 'text', None), 'value', None)
        if reference:
            result.append(str(reference))
    return sorted(set(result))


class SeriesPathDialog:
    def __init__(self, parent, inventory, board_path, existing=None):
        import wx
        from wayricad_runtime.readable_choice import ReadableChoice
        self.wx = wx;self.inventory=inventory;self.board_path=board_path;self.request=None
        self.branches=list(existing.get('branches', [])) if existing else []
        self.dialog=wx.Dialog(parent,title='Quick PI · Series path editor',
                              size=parent.FromDIP((930,700)),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        root=wx.BoxSizer(wx.VERTICAL)
        intro=wx.StaticText(self.dialog,label='Choose source and sink pads, then add two-pad components in path order. Values are explicit assumptions; saved copper supplies the intervening nets.')
        intro.Wrap(parent.FromDIP(880));root.Add(intro,0,wx.EXPAND|wx.ALL,12)
        labels=sorted(row['label'] for row in inventory.get('terminals', []))
        endpoints=wx.BoxSizer(wx.HORIZONTAL)
        self.source=ReadableChoice(self.dialog,choices=labels);self.sink=ReadableChoice(self.dialog,choices=labels)
        if labels:self.source.SetSelection(0);self.sink.SetSelection(min(1,len(labels)-1))
        for name,ctrl in (('Source pad',self.source),('Sink pad',self.sink)):
            endpoints.Add(wx.StaticText(self.dialog,label=name),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,6)
            endpoints.Add(ctrl,1,wx.RIGHT,12)
        select=wx.Button(self.dialog,label='Use KiCad selected pads');endpoints.Add(select,0)
        select.Bind(wx.EVT_BUTTON,self._selection)
        root.Add(endpoints,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        main=wx.BoxSizer(wx.HORIZONTAL)
        left=wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(self.dialog,label='Ordered component path'),0,wx.BOTTOM,5)
        self.list=wx.ListBox(self.dialog);left.Add(self.list,1,wx.EXPAND)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        for title,handler in (('Remove',self._remove),('Move up',self._up),('Move down',self._down)):
            button=wx.Button(self.dialog,label=title);button.Bind(wx.EVT_BUTTON,handler);actions.Add(button,0,wx.RIGHT,5)
        left.Add(actions,0,wx.TOP,7);main.Add(left,1,wx.EXPAND|wx.RIGHT,14)
        self.parallel_button=wx.Button(self.dialog,label='Parallel parts…')
        self.parallel_button.Bind(wx.EVT_BUTTON,self._parallel)
        left.Add(self.parallel_button,0,wx.EXPAND|wx.TOP,7)
        self.list.Bind(wx.EVT_LISTBOX,self._parallel_note)
        right=wx.BoxSizer(wx.VERTICAL)
        right.Add(wx.StaticText(self.dialog,label='Add next component'),0,wx.BOTTOM,5)
        self.component=ReadableChoice(self.dialog);right.Add(self.component,0,wx.EXPAND|wx.BOTTOM,10)
        self.kind=ReadableChoice(self.dialog,choices=['Resistance / RL','Fixed forward drop','Diode at DC current'])
        self.kind.SetSelection(0);right.Add(self.kind,0,wx.EXPAND|wx.BOTTOM,10)
        self.values={};grid=wx.FlexGridSizer(0,2,6,9);grid.AddGrowableCol(1,1)
        for key,title,initial in (('r','Resistance (e.g. 5mΩ)','5m'),('l','Inductance (e.g. 1mH)',''),
                                  ('fixed','Fixed forward drop','1V'),('vf','Vf at Iref','0.7V'),
                                  ('iref','Reference current','1A'),('n','Ideality n','2'),('t','Junction temperature','25C')):
            label=wx.StaticText(self.dialog,label=title);control=wx.TextCtrl(self.dialog,value=initial)
            grid.Add(label,0,wx.ALIGN_CENTER_VERTICAL);grid.Add(control,1,wx.EXPAND)
            self.values[key]=(label,control)
        right.Add(grid,0,wx.EXPAND|wx.BOTTOM,8)
        add_actions=wx.BoxSizer(wx.HORIZONTAL)
        selected_component=wx.Button(self.dialog,label='Use selected component')
        selected_component.Bind(wx.EVT_BUTTON,self._selected_component)
        add_actions.Add(selected_component,0,wx.RIGHT,8)
        add=wx.Button(self.dialog,label='Add component to path');add.Bind(wx.EVT_BUTTON,self._add)
        add_actions.Add(add,0);right.Add(add_actions,0,wx.ALIGN_RIGHT);main.Add(right,1,wx.EXPAND)
        root.Add(main,1,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        root.Add(wx.StaticText(self.dialog,label='Preview and validation'),0,wx.LEFT|wx.TOP,12)
        self.preview=wx.TextCtrl(self.dialog,style=wx.TE_MULTILINE|wx.TE_READONLY,size=(-1,100))
        root.Add(self.preview,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,12)
        footer=wx.BoxSizer(wx.HORIZONTAL)
        save=wx.Button(self.dialog,label='Save path…');load=wx.Button(self.dialog,label='Load path…')
        save.Bind(wx.EVT_BUTTON,self._save);load.Bind(wx.EVT_BUTTON,self._load)
        footer.Add(load,0,wx.RIGHT,7);footer.Add(save,0)
        footer.AddStretchSpacer()
        run=wx.Button(self.dialog,wx.ID_OK,label='Run this path');cancel=wx.Button(self.dialog,wx.ID_CANCEL,label='Cancel')
        run.Bind(wx.EVT_BUTTON,self._run);footer.Add(run,0,wx.RIGHT,8);footer.Add(cancel,0)
        root.Add(footer,0,wx.EXPAND|wx.ALL,12)
        self.dialog.SetSizer(root)
        self.source.Bind(wx.EVT_CHOICE,self._changed);self.sink.Bind(wx.EVT_CHOICE,self._changed)
        self.kind.Bind(wx.EVT_CHOICE,self._changed)
        self._changed()

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

    def _parsed(self):
        from .console import parse_command
        from .parallel_parts import with_parallel
        return with_parallel(parse_command(build_command(self._chosen(self.source),self._chosen(self.sink),self.branches),self.inventory),self.branches,self.inventory)

    def _parallel(self,event):
        from .parallel_parts import suggested_resistance
        from .console import _model
        wx=self.wx;index=self.list.GetSelection()
        try:parts=self._parallel_candidates(index)
        except (ValueError,KeyError) as exc:self.preview.SetValue(str(exc));return
        dialog=wx.Dialog(self.dialog,title='Review parallel components',size=(680,440),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        layout=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(dialog,label='These two-pad parts span exactly the same saved net pair. Check parts to include and review each R/L model. Capacitor, diode and unknown DCR models are not guessed.')
        note.Wrap(630);layout.Add(note,0,wx.EXPAND|wx.ALL,10)
        area=wx.ScrolledWindow(dialog,style=wx.VSCROLL);area.SetScrollRate(0,12);grid=wx.FlexGridSizer(0,2,8,12);grid.AddGrowableCol(1)
        selected={row['footprint_uuid']:row for row in self.branches[index].get('parallel',[])}
        controls=[]
        for part in parts:
            old=selected.get(part['footprint_uuid'],{})
            check=wx.CheckBox(area,label=part['id']+' · '+str(part['component_value']))
            check.SetValue(bool(old));text=wx.TextCtrl(area,value=old.get('model',suggested_resistance(part)))
            text.SetHint('Explicit model, e.g. 100m or 10mH+30m')
            grid.Add(check,0,wx.ALIGN_CENTER_VERTICAL);grid.Add(text,1,wx.EXPAND);controls.append((part,check,text))
        area.SetSizer(grid);layout.Add(area,1,wx.EXPAND|wx.ALL,10)
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
            for part,check,text in controls:
                if not check.GetValue():continue
                model=text.GetValue().strip();parsed=_model(model)
                if 'diode' in parsed or 'fixed_drop_v' in parsed:raise ValueError('Parallel DC stages require R/L models.')
                reviewed.append({'footprint_uuid':part['footprint_uuid'],'model':model})
            self.branches[index]['parallel']=reviewed;self._changed();self.list.SetSelection(index);self._parallel_note()
        except ValueError as exc:wx.MessageBox(str(exc),'Review parallel models',wx.OK|wx.ICON_WARNING)
        finally:dialog.Destroy()

    def _chosen(self,control):
        return control.GetStringSelection() if control.GetSelection()>=0 else ''

    def _cursor_net(self):
        label=self._chosen(self.source)
        row=next((row for row in self.inventory.get('terminals',[]) if row['label']==label),None)
        if row is None:return ''
        net=row['net']
        for branch in self.branches:
            choice=next((other for ref,other in compatible_components(self.inventory,net)
                         if ref==branch['reference']),None)
            if choice is None:return ''
            net=choice
        return net

    def _changed(self,event=None):
        wx=self.wx
        active=self.kind.GetSelection()
        for key,(label,control) in self.values.items():
            show=key in (('r','l') if active==0 else ('fixed',) if active==1 else ('vf','iref','n','t'))
            label.Show(show);control.Show(show)
        self.dialog.Layout()
        net=self._cursor_net();used={item['reference'] for item in self.branches}
        self.candidates=compatible_components(self.inventory,net,used) if net else []
        self.component.Set([ref+' · '+net+' → '+next_net for ref,next_net in self.candidates])
        if self.candidates:self.component.SetSelection(0)
        self.list.Set([row['reference']+'  ·  '+row['model']+(f" (+{len(row['parallel'])} parallel)" if row.get('parallel') else '') for row in self.branches])
        if self.branches:self.list.SetSelection(len(self.branches)-1)
        self._parallel_note()
        try:
            command=build_command(self._chosen(self.source),self._chosen(self.sink),self.branches)
            parsed=self._parsed()
            found=[part['id'] for i in range(len(self.branches)) for part in self._parallel_candidates(i)]
            self.preview.SetValue(command+'\n\nValid saved-net path · '+str(len(parsed['series']))+' series stage(s).'+
                                  ('\nDetected parallel parts: '+', '.join(found)+' · review with Parallel parts.' if found else ''))
        except Exception as exc:
            self.preview.SetValue((command if 'command' in locals() else '')+'\n\nReview: '+str(exc))
        if event:event.Skip()

    def _model(self):
        def value(key):return self.values[key][1].GetValue().strip()
        kind=self.kind.GetSelection()
        if kind==0:
            pieces=[piece for piece in (value('r'),value('l')) if piece]
            if not pieces:raise ValueError('Enter resistance or inductance.')
            return '+'.join(pieces)
        if kind==1:return value('fixed')
        return f"diode(Vf={value('vf')},Iref={value('iref')},n={value('n')},T={value('t')})"

    def _add(self,event):
        if self.component.GetSelection()<0:return
        reference=self.candidates[self.component.GetSelection()][0]
        model=self._model()
        from .console import _model
        try:_model(model)
        except ValueError as exc:self.wx.MessageBox(str(exc),'Invalid component model',self.wx.OK|self.wx.ICON_WARNING);return
        self.branches.append({'reference':reference,'model':model});self._changed()

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
            labels=selected_pad_labels(self.board_path,self.inventory)
            if not labels:raise ValueError('Select one or two saved-board pads in the originating PCB Editor, then retry.')
            for control,label in ((self.source,labels[0]),(self.sink,labels[1] if len(labels)>1 else '')):
                if label:control.SetStringSelection(label)
            self._changed()
            if len(labels)>2:self.wx.MessageBox('More than two pads are selected. The first two were used; review their order.','Selection review')
        except Exception as exc:self.wx.MessageBox(str(exc),'KiCad selection',self.wx.OK|self.wx.ICON_WARNING)

    def _save(self,event):
        data={'schema':1,'source':self._chosen(self.source),'sink':self._chosen(self.sink),'branches':self.branches}
        with self.wx.FileDialog(self.dialog,'Save series path',defaultDir=str(Path(self.board_path).parent),
             wildcard='JSON (*.json)|*.json',style=self.wx.FD_SAVE|self.wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=self.wx.ID_OK:return
            Path(dialog.GetPath()).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')

    def _load(self,event):
        with self.wx.FileDialog(self.dialog,'Load series path',defaultDir=str(Path(self.board_path).parent),
             wildcard='JSON (*.json)|*.json',style=self.wx.FD_OPEN|self.wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=self.wx.ID_OK:return
            try:
                data=json.loads(Path(dialog.GetPath()).read_text(encoding='utf-8'))
                if data.get('schema')!=1 or not isinstance(data.get('branches'),list):raise ValueError('Unsupported series-path file.')
                command=build_command(data['source'],data['sink'],data['branches'])
                from .console import parse_command
                parse_command(command,self.inventory)
                self.source.SetStringSelection(data['source']);self.sink.SetStringSelection(data['sink'])
                self.branches=list(data['branches']);self._changed()
            except (OSError,KeyError,TypeError,ValueError) as exc:
                self.wx.MessageBox(str(exc),'Cannot load path',self.wx.OK|self.wx.ICON_WARNING)

    def _run(self,event):
        try:
            self.request=self._parsed()
            self.dialog.EndModal(self.wx.ID_OK)
        except ValueError as exc:self.wx.MessageBox(str(exc),'Review the series path',self.wx.OK|self.wx.ICON_WARNING)

    def show(self):
        try:return self.request if self.dialog.ShowModal()==self.wx.ID_OK else None
        finally:self.dialog.Destroy()
