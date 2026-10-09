"""Native coupled-study setup, plots, diagnostics and offline export."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import threading
import wx
from matplotlib.figure import Figure
from .electrothermal_report import draw, summary, valid_operating_point, write_report


def initial_studies(electrical, terminals=()):
    from .transient_inputs import initial_study
    steady = {'electrical': copy.deepcopy(electrical),
        'thermal_settings': {'ambient_c': 20., 'dielectric_k_w_mk': None,
            'copper_k_w_mk': 385., 'via_plating_mm': electrical.get('plating_mm', .025),
            'grid_cells_long_axis': 48, 'board_h_w_m2k': None, 'board_emissivity': None},
        'coupling': {'material_temperature_range_c': [-40., 150.], 'temperature_cap_c': 105.,
            'max_iterations': 60, 'relaxation': .5, 'temperature_tolerance_c': .01,
            'loss_relative_tolerance': 1e-5}}
    for key in ('action', 'board_path', 'source_sha256'):
        steady['electrical'].pop(key, None)
    transient = initial_study(electrical, terminals)
    transient.update(exchange_step_s=.001, ambient_c=20.,
        thermal_nodes=[{'id': 'rail', 'label': 'Reviewed rail heat path',
            'resistance_K_W': None, 'capacitance_J_K': None, 'initial_temperature_c': 20.,
            'initial_power_W': 0., 'step_power_W': 0., 'step_time_s': 0., 'max_temperature_c': 105.}],
        resistance_mappings=[{'element_id': 'source', 'thermal_node_id': 'rail',
            'reference_temperature_c': 20., 'alpha_per_K': .00393,
            'min_temperature_c': -40., 'max_temperature_c': 150.}])
    return {'steady': steady, 'transient': transient}


class ElectrothermalStudyDialog(wx.Dialog):
    def __init__(self, parent, initial, runner, canvas_types, board_path=None, source_sha256=None):
        super().__init__(parent, title='Quick PI · Electrothermal study', size=(1120, 800),
                         style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetMinSize((820, 600)); self.runner=runner; self.initial=copy.deepcopy(initial)
        self.board_path=board_path; self.sha=source_sha256; self.result=None
        self._busy=False; self._closed=False; self._closing=False; self._cancel=threading.Event()
        self.input_path=None; self.input_sha=None
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='Steady: saved copper losses and layer temperatures feed back into resistance. '
            'Transient: explicit R/L/C paths and thermal R/C nodes retain their states. '
            'Enter missing physical inputs; source current budgets remain diagnostic.')
        note.Wrap(1060); root.Add(note,0,wx.EXPAND|wx.ALL,10)
        choices=wx.BoxSizer(wx.HORIZONTAL)
        self.mode=wx.Choice(self,choices=['Steady saved-board coupling','Transient lumped coupling']); self.mode.SetSelection(0)
        self.load=wx.Button(self,label='Load study JSON…'); self.reset=wx.Button(self,label='Reset selected model')
        for control in (self.mode,self.load,self.reset): choices.Add(control,0,wx.RIGHT,8)
        root.Add(choices,0,wx.ALL,10)
        self.book=wx.Notebook(self)
        self.setup=wx.TextCtrl(self.book,style=wx.TE_MULTILINE|wx.TE_DONTWRAP)
        self.setup.ChangeValue(json.dumps(initial['steady'],indent=2,allow_nan=False)); self.book.AddPage(self.setup,'Explicit model inputs')
        panel=wx.Panel(self.book); layout=wx.BoxSizer(wx.VERTICAL); self.figure=Figure(figsize=(10,6))
        Canvas,Toolbar=canvas_types; self.canvas=Canvas(panel,wx.ID_ANY,self.figure); toolbar=Toolbar(self.canvas); toolbar.Realize()
        layout.Add(self.canvas,1,wx.EXPAND); layout.Add(toolbar,0,wx.EXPAND); panel.SetSizer(layout); self.book.AddPage(panel,'Coupled results')
        self.details=wx.TextCtrl(self.book,style=wx.TE_MULTILINE|wx.TE_READONLY); self.book.AddPage(self.details,'Checks and solve actions')
        root.Add(self.book,1,wx.EXPAND|wx.LEFT|wx.RIGHT,10)
        self.status=wx.StaticText(self,label='null marks an input you must supply. Review thermal/material assumptions before running.'); self.status.Wrap(1060)
        root.Add(self.status,0,wx.EXPAND|wx.ALL,10)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        self.run=wx.Button(self,label='Run electrothermal'); self.stop=wx.Button(self,label='Cancel run')
        self.export=wx.Button(self,label='Export HTML / JSON…'); close=wx.Button(self,wx.ID_CLOSE,label='Close')
        for control in (self.run,self.stop,self.export,close): actions.Add(control,0,wx.RIGHT,8)
        root.Add(actions,0,wx.ALIGN_RIGHT|wx.ALL,10); self.SetSizer(root)
        self.setup.Bind(wx.EVT_TEXT,self._changed); self.mode.Bind(wx.EVT_CHOICE,self._reset)
        self.reset.Bind(wx.EVT_BUTTON,self._reset); self.load.Bind(wx.EVT_BUTTON,self._load)
        self.run.Bind(wx.EVT_BUTTON,self._run); self.stop.Bind(wx.EVT_BUTTON,lambda e:self._cancel.set())
        self.export.Bind(wx.EVT_BUTTON,self._export); close.Bind(wx.EVT_BUTTON,self._close); self.Bind(wx.EVT_CLOSE,self._close)
        self.stop.Disable(); self.export.Disable()

    def _kind(self): return 'steady' if self.mode.GetSelection()==0 else 'transient'

    def _invalidate(self):
        self.result=None; self.export.Disable(); self.figure.clear(); self.canvas.draw_idle(); self.details.ChangeValue('')

    def _changed(self,event=None):
        self.input_path=None; self.input_sha=None; self._invalidate(); self.status.SetLabel('Inputs changed. Rerun electrothermal coupling.')
        if event: event.Skip()

    def _reset(self,event=None):
        self.setup.ChangeValue(json.dumps(self.initial[self._kind()],indent=2,allow_nan=False)); self._changed()

    def _load(self,event=None):
        from .electrothermal_cli import load_study
        with wx.FileDialog(self,'Load electrothermal study',wildcard='JSON study (*.json)|*.json',style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
        try:
            envelope, sha=load_study(path); self.mode.SetSelection(0 if envelope['mode']=='steady' else 1)
            self.setup.ChangeValue(json.dumps(envelope['study'],indent=2,allow_nan=False))
            self._changed(); self.input_path=path; self.input_sha=sha; self.status.SetLabel('Loaded study. Review its model inputs and mappings before running.')
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc))

    def _request(self):
        text=self.setup.GetValue()
        if len(text.encode('utf-8'))>4*1024*1024: raise ValueError('Model inputs exceed 4 MiB.')
        # Reuse strict intake without writing UI input to a shared temporary path.
        from .electrothermal_cli import parse_envelope
        envelope=parse_envelope(('{"mode":'+json.dumps(self._kind())+',"study":'+text+'}').encode('utf-8'))
        request={'action':'electrothermal',**envelope}
        if self.board_path: request.update(board_path=str(self.board_path),source_sha256=self.sha)
        if self.input_path: request.update(study_input_path=self.input_path,study_file_sha256=self.input_sha)
        return request

    def _run(self,event=None):
        if self._busy:return
        try: request=self._request()
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc));return
        self._invalidate(); self._busy=True; self._cancel.clear(); self.run.Disable(); self.stop.Enable()
        for control in (self.mode,self.setup,self.load,self.reset): control.Disable()
        self.status.SetLabel('Running coupled models. Cancellation discards partial results.')
        def work():
            result=None; error=None
            try: result=self.runner(copy.deepcopy(request),self._cancel.is_set)
            except Exception as exc:error=str(exc)
            if not self._closed: wx.CallAfter(self._finished,result,error)
        threading.Thread(target=work,daemon=True).start()

    def _finished(self,result,error):
        self._busy=False
        if self._closed:return
        self.run.Enable(); self.stop.Disable()
        for control in (self.mode,self.setup,self.load,self.reset):control.Enable()
        if self._closing:self._finish_close();return
        if self._cancel.is_set():error='Coupled study cancelled. No partial result accepted.'
        if not error and (not isinstance(result,dict) or 'electrothermal' not in result):error='Worker returned no coupled result.'
        if error:self.status.SetLabel(error);return
        self.result=result; draw(self.figure,result); self.canvas.draw_idle(); self.details.ChangeValue(summary(result))
        self.book.SetSelection(1); self.export.Enable()
        self.status.SetLabel(('Operating checks accepted. ' if valid_operating_point(result) else 'Checks failed or limits violated. ')+
                             str(result['electrothermal']['status'])+' · review Checks and solve actions.')

    def _export(self,event=None):
        if not self.result:return
        with wx.FileDialog(self,'Export electrothermal evidence',defaultFile='electrothermal.html',wildcard='HTML (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK:return
            path=dialog.GetPath()
        if Path(path).with_suffix('.json').exists() and wx.MessageBox('Replace the existing paired JSON report?','Paired report exists',wx.YES_NO|wx.NO_DEFAULT,self)!=wx.YES:return
        try: write_report(path,self.result); self.status.SetLabel('Exported '+path)
        except (ValueError,OSError) as exc:self.status.SetLabel(str(exc))

    def _close(self,event=None):
        if self._busy:
            self._closing=True; self._cancel.set(); self.status.SetLabel('Cancelling the worker before closing…')
            if event and hasattr(event,'CanVeto') and event.CanVeto():event.Veto()
            return
        self._finish_close()

    def _finish_close(self):
        self._closed=True
        if self.IsModal():self.EndModal(wx.ID_CLOSE)
        else:self.Destroy()
