"""Explicit rail and shared-return study editor with bounded worker lifecycle."""
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
        super().__init__(parent,title='Quick PI · Multi-net DC studies',size=(1000,740),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetMinSize((700,500));self.runner=runner;self.inventory=inventory
        self.board_path=str(board_path);self.sha=source_sha256;self.result=None
        self._busy=False;self._closed=False;self._closing=False;self._cancel=threading.Event()
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='1 Add the power rails.  2 Set up ground / return copper.  3 Run and review voltage drop and losses. '
            'A return setup can serve one rail or several rails sharing the same ground.')
        note.Wrap(930);root.Add(note,0,wx.EXPAND|wx.ALL,10)
        row=wx.WrapSizer(wx.HORIZONTAL)
        self.add=wx.Button(self,label='Add net case…');self.load=wx.Button(self,label='Load JSON…');self.save=wx.Button(self,label='Save study JSON…')
        self.units=wx.Button(self,label='Edit source / load pads…');self.returns=wx.Button(self,label='Set up ground / return…')
        for control in (self.add,self.units,self.returns,self.load,self.save):row.Add(control,0,wx.RIGHT|wx.BOTTOM,6)
        root.Add(row,0,wx.LEFT|wx.RIGHT,10)
        self.book=wx.Notebook(self)
        guided=wx.Panel(self.book);guided_layout=wx.BoxSizer(wx.VERTICAL)
        guided_layout.Add(wx.StaticText(guided,label='Power rails'),0,wx.ALL,8)
        self.case_table=wx.ListCtrl(guided,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(label,width) in enumerate([('Case / rail',220),('Net',180),('Loads',90),('Ground / return',310)]):self.case_table.InsertColumn(i,label,width=width)
        guided_layout.Add(self.case_table,1,wx.EXPAND|wx.LEFT|wx.RIGHT,8)
        guided_layout.Add(wx.StaticText(guided,label='Ground / return setups'),0,wx.ALL,8)
        self.return_table=wx.ListCtrl(guided,style=wx.LC_REPORT|wx.LC_SINGLE_SEL)
        for i,(label,width) in enumerate([('Setup',210),('Return net',160),('Power rail(s)',260),('Pad mapping',250)]):self.return_table.InsertColumn(i,label,width=width)
        guided_layout.Add(self.return_table,1,wx.EXPAND|wx.LEFT|wx.RIGHT,8)
        return_actions=wx.BoxSizer(wx.HORIZONTAL)
        self.edit_return=wx.Button(guided,label='Edit selected return…');self.remove_return=wx.Button(guided,label='Remove selected return')
        for control in (self.edit_return,self.remove_return):return_actions.Add(control,0,wx.RIGHT,8)
        guided_layout.Add(return_actions,0,wx.ALL,8)
        self.setup_note=wx.StaticText(guided);self.setup_note.Wrap(900);guided_layout.Add(self.setup_note,0,wx.EXPAND|wx.ALL,8)
        guided.SetSizer(guided_layout);self.book.AddPage(guided,'1 · Rails and returns')
        self.details=wx.TextCtrl(self.book,style=wx.TE_MULTILINE|wx.TE_READONLY)
        self.book.AddPage(self.details,'2 · Results')
        self.setup=wx.TextCtrl(self.book,value=json.dumps(initial,indent=2,allow_nan=False),style=wx.TE_MULTILINE|wx.TE_DONTWRAP)
        self.book.AddPage(self.setup,'Advanced JSON')
        catalog=wx.TextCtrl(self.book,value='\n'.join(t.get('net','')+' · '+t.get('label',t['id']) for t in inventory.get('terminals',[])),
                            style=wx.TE_MULTILINE|wx.TE_READONLY)
        self.book.AddPage(catalog,'Saved-board pad catalogue')
        root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.status=wx.StaticText(self,label='Select a rail and Set up ground / return. Advanced numerical and thermal settings remain in the JSON tab.')
        self.status.Wrap(930);root.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        self.run=wx.Button(self,label='Run all cases');self.stop=wx.Button(self,label='Cancel');self.export=wx.Button(self,label='Export HTML / JSON…');close=wx.Button(self,wx.ID_CLOSE,'Close')
        self.power_flow=wx.Button(self,label='Power flow…')
        self.power_flow.SetToolTip('Source-to-sink power budget; common return losses counted once')
        for control in (self.run,self.stop,self.export,self.power_flow,close):actions.Add(control,0,wx.RIGHT,8)
        root.Add(actions,0,wx.ALIGN_RIGHT|wx.ALL,10);self.SetSizer(root)
        self.setup.Bind(wx.EVT_TEXT,self.changed);self.add.Bind(wx.EVT_BUTTON,self.add_case)
        self.units.Bind(wx.EVT_BUTTON,self.edit_units);self.returns.Bind(wx.EVT_BUTTON,self.add_shared_return)
        self.edit_return.Bind(wx.EVT_BUTTON,self.edit_selected_return);self.remove_return.Bind(wx.EVT_BUTTON,self.remove_selected_return)
        self.return_table.Bind(wx.EVT_LIST_ITEM_ACTIVATED,self.edit_selected_return)
        self.load.Bind(wx.EVT_BUTTON,self.load_study);self.save.Bind(wx.EVT_BUTTON,self.save_study)
        self.run.Bind(wx.EVT_BUTTON,self.run_cases);self.stop.Bind(wx.EVT_BUTTON,lambda e:self._cancel.set())
        self.export.Bind(wx.EVT_BUTTON,self.export_report);close.Bind(wx.EVT_BUTTON,self.close);self.Bind(wx.EVT_CLOSE,self.close)
        self.power_flow.Bind(wx.EVT_BUTTON,self.show_power_flow)
        self.stop.Disable();self.export.Disable();self.refresh_summary();fit_to_display(self);install_accessibility(self,Path(__file__).with_name('help.html'))

    def changed(self,event=None):
        self.result=None;self.export.Disable();self.details.Clear()
        self.refresh_summary()
        self.status.SetLabel('Study changed. Rerun every case before exporting.')
        if event:event.Skip()

    def show_power_flow(self,event=None):
        if self._busy or not self.result:
            self.status.SetLabel('Run the current study before viewing power flow.');return
        try:
            from .sankey import open_sankey
            open_sankey(self.result)
        except Exception as exc:self.status.SetLabel('Power flow: '+str(exc))

    def study(self):return parse_study(self.setup.GetValue().encode('utf-8'))

    def refresh_summary(self):
        """Present saved case identities and return mappings without requiring JSON."""
        from .service import sink_requests
        self.case_table.DeleteAllItems();self.return_table.DeleteAllItems();self._return_rows=[]
        try:study=self.study()
        except ValueError as exc:self.setup_note.SetLabel('Advanced JSON needs correction: '+str(exc));return
        returns={}
        for i,group in enumerate(study.get('shared_returns',[])):
            members=sorted({m['case'] for m in group['loads']})
            for name in members:returns[name]=group['net']+' · shared' if len(members)>1 else group['net']
            row=self.return_table.InsertItem(self.return_table.GetItemCount(),group['name'])
            self.return_table.SetItem(row,1,group['net']);self.return_table.SetItem(row,2,', '.join(members))
            self.return_table.SetItem(row,3,str(len(group['loads']))+' load unit(s)');self._return_rows.append(('shared',i))
        missing=0
        for case in study['cases']:
            if 'return_conduction' in case:
                definition=case['return_conduction'];returns[case['name']]=definition['net']+' · independent loop'
                row=self.return_table.InsertItem(self.return_table.GetItemCount(),case['name']+' ground')
                self.return_table.SetItem(row,1,definition.get('net','Unknown'));self.return_table.SetItem(row,2,case['name'])
                self.return_table.SetItem(row,3,'Existing independent loop');self._return_rows.append(('independent',case['name']))
            row=self.case_table.InsertItem(self.case_table.GetItemCount(),case['name'])
            self.case_table.SetItem(row,1,case['electrical']['net'])
            try:load_count=str(len(sink_requests(case['electrical'])))
            except ValueError:load_count='Review loads'
            self.case_table.SetItem(row,2,load_count)
            self.case_table.SetItem(row,3,returns.get(case['name'],'Not configured'))
            missing+=case['name'] not in returns
        if self.case_table.GetItemCount():self.case_table.Select(0)
        if self.return_table.GetItemCount():self.return_table.Select(0)
        self.edit_return.Enable(bool(self._return_rows));self.remove_return.Enable(bool(self._return_rows))
        self.setup_note.SetLabel((str(missing)+' rail(s) have no DC return solve. ' if missing else 'All rails have a return setup. ')+
            'A geometric return-path review is separate from this DC return-current calculation.')

    def apply_study(self,study):
        validate_study(study);self.setup.SetValue(json.dumps(study,indent=2,allow_nan=False));self.refresh_summary()

    def choose_pads(self,net,title,selected=()):
        from .pi_return_setup import choose_pad_unit
        self.status.SetLabel(title+' · choose the physical pads; their combined current belongs to one unit.')
        return choose_pad_unit(self,self.inventory,net,selected)

    def edit_units(self,event=None):
        """Discoverable grouped-pad editor; raw JSON remains the exact saved contract."""
        try:
            study=self.study()
            with wx.SingleChoiceDialog(self,'Select the rail case','Pad units',[c['name'] for c in study['cases']]) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                case=study['cases'][dialog.GetSelection()]
            from .service import sink_requests
            from .terminals import pad_names,source_names
            electrical=case['electrical'];sinks=sink_requests(electrical)
            labels=['Source unit']+['Load '+s.get('id',str(i+1)) for i,s in enumerate(sinks)]+['Add load unit']
            with wx.SingleChoiceDialog(self,'Select a unit to edit. Load current is the total across its selected pads.','Pad units',labels) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                selection=dialog.GetSelection()
            if selection==0:
                chosen=self.choose_pads(electrical['net'],'Source pads',source_names(electrical))
                if chosen is None:return
                electrical.pop('source_terminal',None);electrical['source_terminals']=chosen
            else:
                index=selection-1;existing=sinks[index] if index<len(sinks) else {}
                chosen=self.choose_pads(electrical['net'],'Load pads',pad_names(existing) if existing else ())
                if chosen is None:return
                with wx.TextEntryDialog(self,'Stable load ID (used in shared-return mappings)','Load unit',existing.get('id','load-'+str(index+1))) as dialog:
                    if dialog.ShowModal()!=wx.ID_OK:return
                    identity=dialog.GetValue().strip()
                with wx.TextEntryDialog(self,'Total current in amperes; FEM determines the pad distribution','Load unit',str(existing.get('current_A',''))) as dialog:
                    if dialog.ShowModal()!=wx.ID_OK:return
                    demand=float(dialog.GetValue())
                load={**existing,'id':identity,'terminals':chosen,'current_A':demand};load.pop('terminal',None)
                if index<len(sinks):sinks[index]=load
                else:sinks.append(load)
                for key in ('sink_terminal','sink_current','sink_min_voltage','sink_max_voltage'):electrical.pop(key,None)
                electrical['sinks']=sinks;sink_requests(electrical)
            validate_study(study);self.setup.SetValue(json.dumps(study,indent=2,allow_nan=False))
        except (ValueError,TypeError) as exc:wx.MessageBox(str(exc),'Pad units',wx.OK|wx.ICON_WARNING,self)

    def add_shared_return(self,event=None):
        if self._busy:return
        try:
            study=self.study();selection=self.case_table.GetFirstSelected()
            case=study['cases'][selection] if 0<=selection<len(study['cases']) else None
            if case and 'return_conduction' in case:
                self.configure_return(study,independent_case=case['name']);return
            for index,group in enumerate(study.get('shared_returns',[])):
                if case and any(m['case']==case['name'] for m in group['loads']):
                    self.configure_return(study,group_index=index);return
            self.configure_return(study,case_names=[case['name']] if case else None)
        except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc))

    def configure_return(self,study,**options):
        from .pi_return_setup import ReturnSetupDialog
        dialog=ReturnSetupDialog(self,study,self.inventory,**options)
        try:
            if dialog.ShowModal()==wx.ID_OK:self.apply_study(dialog.updated)
        finally:dialog.Destroy()

    def edit_selected_return(self,event=None):
        if self._busy:return
        index=self.return_table.GetFirstSelected()
        if not 0<=index<len(self._return_rows):return
        kind,identity=self._return_rows[index]
        try:self.configure_return(self.study(),**({'group_index':identity} if kind=='shared' else {'independent_case':identity}))
        except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc))

    def remove_selected_return(self,event=None):
        if self._busy:return
        index=self.return_table.GetFirstSelected()
        if not 0<=index<len(self._return_rows):return
        if wx.MessageBox('Remove this staged return setup? The power rails and PCB stay unchanged.',
                         'Remove return setup',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_QUESTION,self)!=wx.YES:return
        try:
            study=self.study();kind,identity=self._return_rows[index]
            if kind=='shared':study['shared_returns'].pop(identity)
            else:next(c for c in study['cases'] if c['name']==identity).pop('return_conduction')
            self.apply_study(study)
        except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc))

    def add_case(self,event=None):
        if self._busy:return
        dialog=wx.Dialog(self,title='Add a rail case',size=(680,650),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        box=wx.BoxSizer(wx.VERTICAL);form=wx.ScrolledWindow(dialog);form.SetScrollRate(8,12)
        fields=wx.FlexGridSizer(cols=2,vgap=10,hgap=10);fields.AddGrowableCol(1)
        net=ReadableComboBox(form,choices=self.inventory.get('nets',[]),style=wx.CB_READONLY)
        source=ReadableChoice(form);sink=ReadableChoice(form);name=wx.TextCtrl(form)
        voltage=wx.TextCtrl(form);current=wx.TextCtrl(form)
        for label,control in [('Case name',name),('Net',net),('Source pad',source),('Load pad',sink),('Source voltage (V)',voltage),('Load demand (A)',current)]:
            fields.Add(wx.StaticText(form,label=label),0,wx.ALIGN_CENTER_VERTICAL);fields.Add(control,1,wx.EXPAND)
        return_enabled=wx.CheckBox(form,label='Set up ground / return after this rail')
        fields.Add(return_enabled,0,wx.EXPAND);fields.AddSpacer(1)
        form.SetSizer(fields);box.Add(form,1,wx.EXPAND|wx.ALL,12)
        box.Add(wx.StaticText(dialog,label='The return setup shows the ground net and all return-pad mappings together. Advanced numerical settings remain in JSON.'),0,wx.ALL,12)
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
                        from .pi_return_setup import ReturnSetupDialog
                        groups=study.get('shared_returns',[]);group_index=None
                        if len(groups)==1:group_index=0
                        elif groups:
                            choices=[g['name']+' · '+g['net'] for g in groups]+['Create a different return domain']
                            with wx.SingleChoiceDialog(dialog,'Which return setup should include this rail?','Ground / return',choices) as picker:
                                if picker.ShowModal()!=wx.ID_OK:continue
                                group_index=picker.GetSelection() if picker.GetSelection()<len(groups) else None
                        members={m['case'] for m in groups[group_index]['loads']} if group_index is not None else set()
                        members.add(study['cases'][-1]['name'])
                        editor=ReturnSetupDialog(dialog,study,self.inventory,group_index=group_index,case_names=members)
                        try:
                            if editor.ShowModal()!=wx.ID_OK:continue
                            study=editor.updated
                        finally:editor.Destroy()
                    self.apply_study(study);return
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
        for control in (self.setup,self.add,self.units,self.returns,self.edit_return,self.remove_return,self.load,self.save):control.Disable()
        self.status.SetLabel('Running rails and simultaneous shared-return groups. Cancel discards the batch.')
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
        for control in (self.setup,self.add,self.units,self.returns,self.edit_return,self.remove_return,self.load,self.save):control.Enable()
        self.refresh_summary()
        if self._cancel.is_set():error='Cancelled; no partial batch accepted.'
        if not error and (not isinstance(result,dict) or 'batch' not in result):error='Worker returned no batch evidence.'
        if error:self.status.SetLabel(error);return
        self.result=result;rows=result['batch']['cases']
        self.details.SetValue('\n\n'.join(row['name']+' · '+row['status']+('\n'+row['error'] if row.get('error') else '') for row in rows))
        if result['batch'].get('shared_returns'):
            self.details.AppendText('\n\nShared-return coupling\n'+json.dumps([{k:v for k,v in group.items() if k not in ('return_conduction','physical_return_potential_V')} for group in result['batch']['shared_returns']],indent=2))
        self.book.SetSelection(1);self.export.Enable()
        self.status.SetLabel(result['batch']['status']+' · '+str(len(rows))+' cases; review shared-return loads, failures and assumptions.')

    def export_report(self,event=None):
        if not self.result:return
        with wx.FileDialog(self,'Export PI cases',defaultFile='pi-cases.html',wildcard='HTML (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            target=dialog.GetPath()
        try:
            from .report import write_batch_report
            write_batch_report(target,self.result);self.status.SetLabel('Exported DC study reports: '+target)
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
