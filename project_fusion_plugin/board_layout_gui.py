"""Independent, review-first dialog for PCB-only imports."""
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import threading
import wx

from .board import board_bounds
from .board_layout import preview_layout_import
from .schematic import new_uuid
from . import sexpr as sx
from .preview import PlacementPreview


class LayoutImportDialog(wx.Dialog):
    def __init__(self,parent,source='',target='',cli_path=''):
        super().__init__(parent,title='Fusion — PCB-only layout import',size=(1060,740),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.cli_path=cli_path;self.plan=None;self.plan_file=None;self.busy=False
        column=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Copy a routed PCB as Board Only footprints and isolated nets. Target schematics and configuration stay unchanged. '
                               'Source outline becomes a drawing guide. Place inside the target outline; preview must introduce no DRC or unconnected findings.')
        note.Wrap(990);column.Add(note,0,wx.EXPAND|wx.ALL,10)
        self.source=wx.FilePickerCtrl(self,path=source,message='Incoming PCB',wildcard='KiCad PCB|*.kicad_pcb',style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL)
        self.target=wx.FilePickerCtrl(self,path=target,message='Target project',wildcard='KiCad project|*.kicad_pro',style=wx.FLP_OPEN|wx.FLP_USE_TEXTCTRL)
        for label,control in [('Incoming PCB',self.source),('Working project',self.target)]:
            column.Add(wx.StaticText(self,label=label),0,wx.LEFT|wx.TOP,10);column.Add(control,0,wx.EXPAND|wx.ALL,10)
            control.Bind(wx.EVT_FILEPICKER_CHANGED,self.invalidate)
        row=wx.BoxSizer(wx.HORIZONTAL)
        self.alias=wx.TextCtrl(self,value='Layout',size=(140,-1))
        self.x=wx.TextCtrl(self,value='20',size=(90,-1));self.y=wx.TextCtrl(self,value='20',size=(90,-1))
        for label,control in [('Net/reference namespace',self.alias),('Left X (mm)',self.x),('Top Y (mm)',self.y)]:
            row.Add(wx.StaticText(self,label=label),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,5);row.Add(control,0,wx.RIGHT,14)
            control.Bind(wx.EVT_TEXT,self.invalidate)
        column.Add(row,0,wx.ALL,10)
        self.preview=PlacementPreview(self);column.Add(self.preview,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.status=wx.StaticText(self,label='Set the source and target, then review placement.');column.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        buttons=wx.BoxSizer(wx.HORIZONTAL)
        self.show=wx.Button(self,label='Show placement');self.validate=wx.Button(self,label='Validate candidate')
        self.apply=wx.Button(self,label='Open Apply Review…');self.apply.Disable()
        for control in (self.show,self.validate,self.apply):buttons.Add(control,0,wx.RIGHT,10)
        buttons.AddStretchSpacer();buttons.Add(wx.Button(self,wx.ID_CLOSE,'Close'))
        column.Add(buttons,0,wx.EXPAND|wx.ALL,10);self.SetSizer(column)
        self.show.Bind(wx.EVT_BUTTON,self.show_placement);self.validate.Bind(wx.EVT_BUTTON,self.validate_candidate)
        self.apply.Bind(wx.EVT_BUTTON,self.apply_candidate)
        self.Bind(wx.EVT_BUTTON,self.finish_close,id=wx.ID_CLOSE)
        self.Bind(wx.EVT_CLOSE,self.close)

    def close(self,event):
        if self.busy:self.status.SetLabel('Wait for the current operation to finish before closing.');return
        event.Skip()

    def finish_close(self,event):
        if self.busy:self.status.SetLabel('Wait for the current operation to finish before closing.');return
        self.EndModal(wx.ID_CLOSE)

    def invalidate(self,event=None):
        self.plan=None;self.plan_file=None;self.apply.Disable();self.preview.clear()
        self.status.SetLabel('Inputs changed; validate a new candidate before applying.')

    def show_placement(self,event):
        try:
            paths=[Path(self.target.GetPath()).with_suffix('.kicad_pcb'),Path(self.source.GetPath())]
            sources=[]
            for index,path in enumerate(paths):
                box=board_bounds(sx.load(path));shift=(0,0) if index==0 else (float(self.x.GetValue())-box[0],float(self.y.GetValue())-box[1])
                sources.append(SimpleNamespace(alias='Target' if index==0 else self.alias.GetValue(),pcb_file=path,
                    bbox=box,translation=shift,hashes={},layer_map={},copper_layers=[]))
            self.preview.show_sources(sources)
            self.status.SetLabel('Placement preview only. Validate candidate runs native target parity and DRC.')
        except Exception as error:self.status.SetLabel(str(error))

    def run(self,action,done):
        self.busy=True
        controls=[self.source,self.target,self.alias,self.x,self.y,self.show,self.validate,self.apply]
        for control in controls:control.Disable()
        def finished(result,error):
            self.busy=False
            for control in controls:control.Enable()
            self.apply.Enable(self.plan is not None)
            if error:self.status.SetLabel(error);return
            done(result)
        def worker():
            try:result=action()
            except Exception as error:wx.CallAfter(finished,None,str(error));return
            wx.CallAfter(finished,result,None)
        threading.Thread(target=worker,name='FusionLayoutImport',daemon=True).start()

    def validate_candidate(self,event):
        try:
            target=self.target.GetPath();source=self.source.GetPath();alias=self.alias.GetValue()
            x,y=float(self.x.GetValue()),float(self.y.GetValue())
            destination=Path(target).resolve().parent.parent/('FusionLayoutReview-'+new_uuid()[:8])
        except Exception as error:self.status.SetLabel(str(error));return
        self.plan=None;self.plan_file=None;self.status.SetLabel('Running native parity, zone refill and DRC…')
        def done(plan):
            path=Path(plan['candidate_directory']).with_name(Path(plan['candidate_directory']).name+'-layout-plan.json')
            try:
                with path.open('x',encoding='utf-8') as stream:
                    json.dump({'format':'wayri-fusion-import-plan-v1','plan':plan},stream,indent=2)
            except Exception as error:self.status.SetLabel('Candidate validated but plan could not be saved: '+str(error));return
            self.plan=plan;self.plan_file=path;self.show_placement(None);self.apply.Enable()
            self.status.SetLabel('Candidate validated. Open Apply Review, then close this dialog and target editors before applying there.')
        self.run(lambda:preview_layout_import(target,source,destination,alias=alias,x_mm=x,y_mm=y,cli_path=self.cli_path),done)

    def apply_candidate(self,event):
        if self.plan is None or self.plan_file is None or self.busy:return
        from .insertion_gui import InsertionDialog
        try:
            launcher=InsertionDialog.python_launcher()
            subprocess.Popen([str(launcher),str(Path(__file__).with_name('insertion_gui.py')),'--plan',str(self.plan_file)],close_fds=True)
            self.status.SetLabel('Apply Review opened independently. Close this dialog and target editors, then apply in that window.')
        except Exception as error:self.status.SetLabel('Could not open Apply Review: '+str(error)+'. Saved plan: '+str(self.plan_file))
