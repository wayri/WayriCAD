"""Shared native study controller; numerical work never touches native boards."""
import json
from pathlib import Path
import tempfile
import threading


def demo_request():
    nx,ny,nz=8,4,3
    return dict(schema_version=1,grid=dict(edges_mm=dict(x=list(range(nx+1)),y=list(range(ny+1)),z=[0,.25,.5,.75])),
        materials={'alloy':dict(thermal_conductivity_w_mk=15.,resistivity_ohm_m=1.09e-6,
            tcr_per_k=.0001,reference_c=20.)},material_ids=['alloy']*(nx*ny*nz),
        fixed_voltage_v={str((z*ny+y)*nx):.01 for z in range(nz) for y in range(ny)} |
                        {str((z*ny+y)*nx+nx-1):0. for z in range(nz) for y in range(ny)},
        fixed_temperature_c={},boundary=dict(ambient_c=20.,h_w_m2k=15.,emissivity=.5),
        settings=dict(temperature_bounds_c=[-50,200],relaxation=.5),
        provenance=dict(source_kind='illustrative-solid-coupon',
            assumptions=['Illustrative constant-property solid, not a product qualification.',
                         'Ideal cell-centre voltage contacts; no contact resistance.',
                         'Thermoelectric effects disabled until explicit Seebeck data are supplied.']))


def open_study(parent=None,request=None,request_factory=None):
    import wx
    from .local_webview import try_new_webview
    from .thermoelectric_study import parse_study,run_study,save_document,load_report,validate_report,MAX_BYTES
    from .thermoelectric_report import render_report

    class StudyFrame(wx.Frame):
        def __init__(self):
            super().__init__(parent,title='3D Electrothermal Study',size=(1180,800))
            self.SetMinSize((760,520));self.report=None;self.closed=False;self.busy=False;self.serial=0
            self.cancel=threading.Event();self.sources=[]
            self.folder=tempfile.TemporaryDirectory(prefix='wayricad-3d-study-')
            panel=wx.Panel(self);layout=wx.BoxSizer(wx.VERTICAL);toolbar=wx.BoxSizer(wx.HORIZONTAL)
            self.buttons={}
            for name,label,handler in [('load','Load study',self.load),('mesh','Generate mesh',self.generate),
                    ('run','Solve 3D',self.run),('cancel','Cancel',self.stop),('json','Export JSON',self.export_json),
                    ('html','Export HTML',self.export_html),('help','Help',self.help)]:
                button=wx.Button(panel,label=label);button.Bind(wx.EVT_BUTTON,handler);toolbar.Add(button,0,wx.RIGHT,5);self.buttons[name]=button
            self.buttons['mesh'].Enable(request_factory is not None)
            layout.Add(toolbar,0,wx.EXPAND|wx.ALL,10)
            split=wx.SplitterWindow(panel,style=wx.SP_LIVE_UPDATE);split.SetMinimumPaneSize(250)
            left=wx.Panel(split);ls=wx.BoxSizer(wx.VERTICAL)
            self.editor=wx.TextCtrl(left,style=wx.TE_MULTILINE|wx.TE_DONTWRAP)
            self.editor.SetValue(json.dumps(request or demo_request(),indent=2))
            self.generated_text=self.editor.GetValue()
            self.editor.Bind(wx.EVT_TEXT,self.changed);ls.Add(self.editor,1,wx.EXPAND)
            self.metrics=wx.ListCtrl(left,style=wx.LC_REPORT)
            self.metrics.InsertColumn(0,'Quantity',width=160);self.metrics.InsertColumn(1,'Value',width=180)
            ls.Add(self.metrics,0,wx.EXPAND|wx.TOP,8);self.metrics.SetMinSize((-1,150));left.SetSizer(ls)
            right=wx.Panel(split);rs=wx.BoxSizer(wx.VERTICAL)
            self.view,reason=try_new_webview(right)
            if self.view:rs.Add(self.view,1,wx.EXPAND)
            else:rs.Add(wx.StaticText(right,label=reason),0,wx.ALL,15)
            right.SetSizer(rs);split.SplitVertically(left,right,370)
            layout.Add(split,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
            self.status=wx.StaticText(panel,label='Ready',style=wx.ST_ELLIPSIZE_END);self.status.SetMinSize((1,-1))
            layout.Add(self.status,0,wx.EXPAND|wx.ALL,10);panel.SetSizer(layout)
            self.Bind(wx.EVT_CLOSE,self.close);self.Bind(wx.EVT_WINDOW_DESTROY,self.destroyed)
            self.update_buttons();self.CentreOnParent()

        def update_buttons(self):
            self.buttons['run'].Enable(not self.busy);self.buttons['load'].Enable(not self.busy)
            self.buttons['mesh'].Enable(not self.busy and request_factory is not None)
            self.buttons['cancel'].Enable(self.busy)
            for key in ('json','html'):self.buttons[key].Enable(not self.busy and self.report is not None)

        def changed(self,event=None):
            self.serial+=1;self.cancel.set();self.report=None;self.metrics.DeleteAllItems()
            if self.view:self.view.SetPage('<html><body>Inputs changed; solve the current study.</body></html>','')
            self.update_buttons()
            if event:event.Skip()

        def generate(self,_event):
            if self.editor.GetValue()!=self.generated_text:
                if wx.MessageBox('Replace the edited or loaded study with a new mesh from the original reviewed heater snapshot?',
                                 'Replace study inputs?',wx.YES_NO|wx.NO_DEFAULT|wx.ICON_WARNING,self)!=wx.YES:return
            try:
                value=json.dumps(request_factory(),indent=2,allow_nan=False)
                self.editor.SetValue(value);self.generated_text=value
            except Exception as exc:self.status.SetLabel(str(exc));self.status.SetToolTip(str(exc))

        def load(self,_event):
            with wx.FileDialog(self,'Load explicit 3D study',wildcard='JSON (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                try:
                    source=Path(dialog.GetPath())
                    if source.stat().st_size>MAX_BYTES:value=load_report(source)
                    else:
                        value=parse_study(source.read_text(encoding='utf-8-sig'))
                        if value.get('schema')=='wayricad.thermoelectric-study/v1':validate_report(value)
                    self.editor.SetValue(json.dumps(value.get('request',value),indent=2));self.sources=[source]
                except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

        def run(self,_event):
            if self.busy:return
            try:study=parse_study(self.editor.GetValue())
            except (ValueError,TypeError) as exc:self.status.SetLabel(str(exc));return
            self.changed();self.cancel=threading.Event();cancel=self.cancel;serial=self.serial
            self.busy=True;self.update_buttons();self.status.SetLabel('Solving current flow and heat balance...')
            def worker():
                result=error=None
                try:result=run_study(study,cancel=cancel)
                except Exception as exc:error=str(exc)
                if not self.closed:wx.CallAfter(self.finished,serial,result,error)
            self.worker=threading.Thread(target=worker,daemon=True,name='3D thermoelectric study');self.worker.start()

        def finished(self,serial,report,error):
            if self.closed:return
            self.busy=False
            if serial!=self.serial:self.status.SetLabel('Inputs changed; stale result discarded.')
            elif error:self.status.SetLabel(error);self.status.SetToolTip(error)
            else:
                self.report=report;r=report['result']
                values=[v for v in r['temperatures_c'] if v is not None]
                for name,value in [('Minimum C',min(values)),('Maximum C',max(values)),('Electrical W',r['electrical_power_w']),('Heat out W',r['heat_out_w']),('Residual W',r['energy_residual_w'])]:
                    index=self.metrics.InsertItem(self.metrics.GetItemCount(),name);self.metrics.SetItem(index,1,f'{value:.7g}')
                try:
                    output=Path(self.folder.name)/'preview.html';output.write_text(render_report(report),encoding='utf-8')
                    if self.view:self.view.LoadURL(output.as_uri())
                    self.status.SetLabel('Converged; review energy balance, source properties and mesh refinement.')
                except Exception as exc:self.status.SetLabel('Solve completed; preview unavailable: '+str(exc))
            self.update_buttons()

        def stop(self,_event):self.cancel.set();self.status.SetLabel('Cancelling...')
        def export_json(self,event):self.export(False)
        def export_html(self,event):self.export(True)
        def export(self,html):
            if not self.report:return
            suffix='html' if html else 'json'
            with wx.FileDialog(self,'Export reviewed 3D result',wildcard=f'{suffix.upper()} (*.{suffix})|*.{suffix}',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal()!=wx.ID_OK:return
                try:save_document(dialog.GetPath(),render_report(self.report) if html else json.dumps(self.report,indent=2,allow_nan=False),sources=self.sources)
                except Exception as exc:self.status.SetLabel(str(exc))

        def help(self,_event):
            from .help import open_help
            open_help(self,Path(__file__).with_name('THERMOELECTRIC_3D.html'))
        def destroyed(self,event):
            if event.GetEventObject() is self:self.closed=True;self.cancel.set()
            event.Skip()
        def close(self,event):
            self.closed=True;self.cancel.set();self.Destroy()
            try:self.folder.cleanup()
            except OSError:pass
    frame=StudyFrame();frame.Show();return frame
