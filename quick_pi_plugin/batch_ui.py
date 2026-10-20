"""Explicit independent-net study editor with bounded worker lifecycle."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import threading
import wx
from wayricad_runtime.readable_choice import ReadableComboBox, ReadableChoice
from wayricad_runtime.layout import fit_to_display, install_accessibility
from .batch import parse_study, validate_study, load_study


class BatchStudyDialog(wx.Dialog):
    def __init__(self,parent,initial,inventory,runner,board_path,source_sha256):
        super().__init__(parent,title='Quick PI · Independent multi-net cases',size=(1000,740),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetMinSize((700,500));self.runner=runner;self.inventory=inventory
        self.board_path=str(board_path);self.sha=source_sha256;self.result=None
        self._busy=False;self._closed=False;self._closing=False;self._cancel=threading.Event()
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Each case has its own net, source and loads. Cases share a saved-board hash, not current or temperature. '
            'DC includes I²R loss; optional return geometry review does not solve a ground-loop voltage drop.')
        note.Wrap(930);root.Add(note,0,wx.EXPAND|wx.ALL,10)
        row=wx.WrapSizer(wx.HORIZONTAL)
        self.add=wx.Button(self,label='Add net case…');self.load=wx.Button(self,label='Load JSON…');self.save=wx.Button(self,label='Save study JSON…')
        for control in (self.add,self.load,self.save):row.Add(control,0,wx.RIGHT|wx.BOTTOM,6)
        root.Add(row,0,wx.LEFT|wx.RIGHT,10)
        self.book=wx.Notebook(self)
        self.setup=wx.TextCtrl(self.book,value=json.dumps(initial,indent=2,allow_nan=False),style=wx.TE_MULTILINE|wx.TE_DONTWRAP)
        self.book.AddPage(self.setup,'Cases and explicit settings')
        self.details=wx.TextCtrl(self.book,style=wx.TE_MULTILINE|wx.TE_READONLY)
        self.book.AddPage(self.details,'Results and failures')
        catalog=wx.TextCtrl(self.book,value='\n'.join(t.get('net','')+' · '+t.get('label',t['id']) for t in inventory.get('terminals',[])),
                            style=wx.TE_MULTILINE|wx.TE_READONLY)
        self.book.AddPage(catalog,'Saved-board pad catalogue')
        root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.status=wx.StaticText(self,label='Add cases with explicit terminals and currents. Advanced return/thermal settings stay visible in JSON.')
        self.status.Wrap(930);root.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        self.run=wx.Button(self,label='Run all cases');self.stop=wx.Button(self,label='Cancel');self.export=wx.Button(self,label='Export HTML / JSON…');close=wx.Button(self,wx.ID_CLOSE,'Close')
        for control in (self.run,self.stop,self.export,close):actions.Add(control,0,wx.RIGHT,8)
        root.Add(actions,0,wx.ALIGN_RIGHT|wx.ALL,10);self.SetSizer(root)
        self.setup.Bind(wx.EVT_TEXT,self.changed);self.add.Bind(wx.EVT_BUTTON,self.add_case)
        self.load.Bind(wx.EVT_BUTTON,self.load_study);self.save.Bind(wx.EVT_BUTTON,self.save_study)
        self.run.Bind(wx.EVT_BUTTON,self.run_cases);self.stop.Bind(wx.EVT_BUTTON,lambda e:self._cancel.set())
        self.export.Bind(wx.EVT_BUTTON,self.export_report);close.Bind(wx.EVT_BUTTON,self.close);self.Bind(wx.EVT_CLOSE,self.close)
        self.stop.Disable();self.export.Disable();fit_to_display(self);install_accessibility(self,Path(__file__).with_name('help.html'))

    def changed(self,event=None):
        self.result=None;self.export.Disable();self.details.Clear()
        self.status.SetLabel('Study changed. Rerun every case before exporting.')
        if event:event.Skip()

    def study(self):return parse_study(self.setup.GetValue().encode('utf-8'))

    def add_case(self,event=None):
        if self._busy:return
        dialog=wx.Dialog(self,title='Add an independent rail case',size=(680,650),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL);form=wx.ScrolledWindow(dialog);form.SetScrollRate(8,12)
        fields=wx.FlexGridSizer(cols=2,vgap=10,hgap=10);fields.AddGrowableCol(1)
        net=ReadableComboBox(form,choices=self.inventory.get('nets',[]),style=wx.CB_READONLY)
        source=ReadableChoice(form);sink=ReadableChoice(form);name=wx.TextCtrl(form)
        voltage=wx.TextCtrl(form);current=wx.TextCtrl(form)
        for label,control in [('Case name',name),('Net',net),('Source pad',source),('Load pad',sink),('Source voltage (V)',voltage),('Load demand (A)',current)]:
            fields.Add(wx.StaticText(form,label=label),0,wx.ALIGN_CENTER_VERTICAL);fields.Add(control,1,wx.EXPAND)
        return_enabled=wx.CheckBox(form,label='Solve explicit DC return copper')
        return_net=ReadableComboBox(form,choices=self.inventory.get('nets',[]),style=wx.CB_READONLY)
        load_ground=ReadableChoice(form);source_ground=ReadableChoice(form)
        fields.Add(return_enabled,0,wx.EXPAND);fields.AddSpacer(1)
        for label,control in [('Return net',return_net),('Load-ground pad (current enters)',load_ground),('Source-ground pad (current leaves)',source_ground)]:
            fields.Add(wx.StaticText(form,label=label),0,wx.ALIGN_CENTER_VERTICAL);fields.Add(control,1,wx.EXPAND);control.Disable()
        def return_changed(event):
            pads=[t for t in self.inventory.get('terminals',[]) if t.get('net')==return_net.GetValue()]
            for control in (load_ground,source_ground):control.SetItems([t['label'] for t in pads])
        return_net.Bind(wx.EVT_COMBOBOX,return_changed)
        def toggle_return(event):
            for control in (return_net,load_ground,source_ground):control.Enable(return_enabled.GetValue())
        return_enabled.Bind(wx.EVT_CHECKBOX,toggle_return)
        form.SetSizer(fields);box.Add(form,1,wx.EXPAND|wx.ALL,12)
        box.Add(wx.StaticText(dialog,label='More sinks and optional return/thermal settings can be edited in the case JSON.'),0,wx.ALL,12)
        box.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,12);dialog.SetSizer(box)
        def changed(e):
            pads=[t for t in self.inventory.get('terminals',[]) if t.get('net')==net.GetValue()]
            source.SetItems([t['label'] for t in pads]);sink.SetItems([t['label'] for t in pads])
            if not name.GetValue():name.SetValue(net.GetValue())
        net.Bind(wx.EVT_COMBOBOX,changed);fit_to_display(dialog)
        try:
            while dialog.ShowModal()==wx.ID_OK:
                try:
                    from .ui import load_values
                    study=self.study()
                    if not net.GetValue() or source.GetSelection()<0 or sink.GetSelection()<0 or source.GetStringSelection()==sink.GetStringSelection():
                        raise ValueError('Choose a net and two different explicit source/load pads.')
                    load=load_values(sink.GetStringSelection(),current.GetValue())
                    value=float(voltage.GetValue())
                    import math
                    if not math.isfinite(value):raise ValueError('Source voltage must be finite.')
                    study['cases'].append({'name':name.GetValue().strip(),'electrical':{
                        'net':net.GetValue(),'source_terminal':source.GetStringSelection(),'source_voltage':value,'sinks':[load]}})
                    if return_enabled.GetValue():
                        if not return_net.GetValue() or min(load_ground.GetSelection(),source_ground.GetSelection())<0:
                            raise ValueError('Select explicit return net and both ground pads.')
                        from .power_loop import return_request
                        definition={'net':return_net.GetValue(),'source_terminal':load_ground.GetStringSelection(),'sink_terminal':source_ground.GetStringSelection()}
                        return_request(study['cases'][-1]['electrical'],definition)
                        study['cases'][-1]['return_conduction']=definition
                    validate_study(study);self.setup.SetValue(json.dumps(study,indent=2,allow_nan=False));return
                except (ValueError,TypeError) as exc:wx.MessageBox(str(exc),'Case settings',wx.OK|wx.ICON_WARNING,dialog)
        finally:dialog.Destroy()

    def load_study(self,event=None):
        with wx.FileDialog(self,'Load PI batch study',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            try:self.setup.SetValue(json.dumps(load_study(dialog.GetPath())[0],indent=2,allow_nan=False))
            except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def save_study(self,event=None):
        try:study=self.study()
        except ValueError as exc:self.status.SetLabel(str(exc));return
        with wx.FileDialog(self,'Save PI batch study',defaultFile='pi-cases.json',wildcard='JSON (*.json)|*.json',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=Path(dialog.GetPath()).resolve()
        import os
        board=Path(self.board_path).resolve()
        if path.suffix.lower()!='.json' or path==board or path.exists() and os.path.samefile(path,board):
            self.status.SetLabel('Use a .json study destination that does not overwrite the PCB.');return
        try:path.write_text(json.dumps(study,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        except OSError as exc:self.status.SetLabel(str(exc))

    def run_cases(self,event=None):
        if self._busy:return
        try:
            study=self.study()
            if hashlib.sha256(Path(self.board_path).read_bytes()).hexdigest()!=self.sha:raise ValueError('Saved PCB changed; close the study and reload.')
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc));return
        self.changed();self._busy=True;self._cancel.clear();self.run.Disable();self.stop.Enable()
        for control in (self.setup,self.add,self.load,self.save):control.Disable()
        self.status.SetLabel('Running bounded independent cases. Cancel discards the batch.')
        request={'action':'batch','study':study,'board_path':self.board_path,'source_sha256':self.sha}
        def work():
            result=None;error=None
            try:result=self.runner(copy.deepcopy(request),self._cancel.is_set)
            except Exception as exc:error=str(exc)
            wx.CallAfter(self.finished,result,error)
        threading.Thread(target=work,daemon=True).start()

    def finished(self,result,error):
        self._busy=False
        if self._closed:return
        if self._closing:self.finish_close();return
        self.run.Enable();self.stop.Disable()
        for control in (self.setup,self.add,self.load,self.save):control.Enable()
        if self._cancel.is_set():error='Cancelled; no partial batch accepted.'
        if not error and (not isinstance(result,dict) or 'batch' not in result):error='Worker returned no batch evidence.'
        if error:self.status.SetLabel(error);return
        self.result=result;rows=result['batch']['cases']
        self.details.SetValue('\n\n'.join(row['name']+' · '+row['status']+('\n'+row['error'] if row.get('error') else '') for row in rows))
        self.book.SetSelection(1);self.export.Enable()
        self.status.SetLabel(result['batch']['status']+' · '+str(len(rows))+' independent cases; review failures, limits and assumptions.')

    def export_report(self,event=None):
        if not self.result:return
        with wx.FileDialog(self,'Export PI cases',defaultFile='pi-cases.html',wildcard='HTML (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            target=dialog.GetPath()
        try:
            from .report import write_batch_report
            write_batch_report(target,self.result);self.status.SetLabel('Exported independent-case reports: '+target)
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def close(self,event=None):
        if self._busy:
            self._closing=True;self._cancel.set();self.status.SetLabel('Cancelling before closing…')
            if event and hasattr(event,'Veto'):event.Veto()
            return
        self.finish_close()

    def finish_close(self):
        self._closed=True
        if self.IsModal():self.EndModal(wx.ID_CLOSE)
        else:self.Destroy()
