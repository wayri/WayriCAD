"""Guided AC/SMPS copper cross-section setup and cancellable native results."""
from __future__ import annotations

import copy
from bisect import bisect_right
import json
import math
from pathlib import Path
import threading

import wx
import wx.grid
from matplotlib.figure import Figure

from .ac_cli import load_study, parse_study, protect_outputs
from .ac_report import draw, summary, write_report, engineering
from .study_setup_file import project_directory


def initial_study():
    """Return a labelled illustrative loop; no values are inferred from a PCB."""
    return {'schema': 'wayricad.pi-ac/v1', 'temperature_c': 20., 'length_mm': 20.,
            'reference_voltage_v': 12., 'dc_current_a': 5.,
            'conductors': [
                {'name': 'Outgoing copper', 'x_mm': 0., 'y_mm': 0.,
                 'width_mm': 2., 'thickness_mm': .07, 'current_scale': 1.},
                {'name': 'Explicit return', 'x_mm': 0., 'y_mm': -.8,
                 'width_mm': 2., 'thickness_mm': .07, 'current_scale': -1.}],
            'harmonics': [{'frequency_hz': 100000., 'current_rms_a': 1.}],
            'mesh_step_mm': .035, 'air_padding_mm': 4., 'max_cells': 50000,
            'convergence_tolerance': .05, 'relative_permittivity': 4.2}


class ACStudyDialog(wx.Dialog):
    """Edit an explicit long-straight-conductor loop without changing the PCB."""
    def __init__(self, parent, runner, canvas_types, board_path=None, source_sha256=None):
        super().__init__(parent, title='Quick PI · AC / SMPS copper study', size=(1140, 850),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((850, 650)); self.runner = runner
        self.board_path = str(board_path) if board_path else None; self.sha = source_sha256
        self.result = None; self.model = initial_study(); self.input_path = None; self.input_sha = None
        self._busy = False; self._closed = False; self._closing = False; self._loading = False
        self._cancel = threading.Event(); self._geometry_artists = []; self._focus = None
        self._cell_lookup = {};self._cell_left = [];self._cell_bottom = []
        root = wx.BoxSizer(wx.VERTICAL)
        self._quick_dirty=False; self._preview_timer=None
        Canvas, Toolbar = canvas_types; self._canvas_type=Canvas
        note = wx.StaticText(self, label='Set the copper loop → add DC and ripple current → review copper heating and voltage drop.\n'
            'Explicit straight-conductor cross-section; PCB routes are not imported. Copper temperature is fixed.')
        note.Wrap(1080); root.Add(note, 0, wx.EXPAND | wx.ALL, 10)
        self.book = wx.Notebook(self); setup = wx.ScrolledWindow(self.book)
        setup.SetScrollRate(10, 10); settings = wx.BoxSizer(wx.VERTICAL)
        self.fields={}; self.input_buttons=[]
        self.setup_mode=wx.Choice(setup,choices=['Quick loop · simple geometry and one ripple frequency','Custom loop · conductor table or SMPS spectrum'])
        self.setup_mode.SetSelection(0);self.setup_mode.Bind(wx.EVT_CHOICE,self._mode_changed)
        mode_row=wx.BoxSizer(wx.HORIZONTAL);mode_row.Add(self.setup_mode,1,wx.RIGHT,8);self.input_buttons.append(self.setup_mode)
        for label,handler in [('Load study…',self._load),('Save inputs…',self._save)]:
            button=wx.Button(setup,label=label);button.Bind(wx.EVT_BUTTON,handler);mode_row.Add(button,0,wx.RIGHT,6);self.input_buttons.append(button)
        settings.Add(mode_row,0,wx.EXPAND|wx.ALL,10)
        self._fields_grid(setup,settings,[('length_mm','Shared conductor length (mm)'),('reference_voltage_v','DC rail voltage (V)'),
                         ('dc_current_a','DC load current (A)'),('temperature_c','Copper temperature (°C)')])
        self._quick_controls(setup,settings)
        self.advanced=wx.CollapsiblePane(setup,label='Custom conductors, SMPS waveform and solver settings',style=wx.CP_DEFAULT_STYLE|wx.CP_NO_TLW_RESIZE)
        self.advanced.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED,lambda event:(setup.Layout(),setup.FitInside()))
        advanced=self.advanced.GetPane();details=wx.BoxSizer(wx.VERTICAL)
        self.conductors = self._grid(advanced, ['Conductor / return', 'Centre x (mm)', 'Centre y (mm)',
                                             'Width (mm)', 'Thickness (mm)', 'Current ×'])
        details.Add(wx.StaticText(advanced,label='Custom copper and return paths · signed current multipliers must sum to zero.'),0,wx.EXPAND|wx.ALL,8)
        details.Add(self.conductors,0,wx.EXPAND|wx.ALL,8)
        self.harmonics=self._grid(advanced,['Frequency (Hz)','Loop ripple RMS (A)'])
        details.Add(wx.StaticText(advanced,label='Distinct RMS harmonics, not peak or peak-to-peak current.'),0,wx.EXPAND|wx.ALL,8)
        details.Add(self.harmonics,0,wx.EXPAND|wx.ALL,8)
        actions=wx.WrapSizer(wx.HORIZONTAL)
        for label,handler in [('Add conductor',lambda e:self._add(self.conductors)),('Remove conductor',lambda e:self._remove(self.conductors)),
                              ('Add harmonic',lambda e:self._add(self.harmonics)),('Remove harmonic',lambda e:self._remove(self.harmonics)),
                              ('Build SMPS waveform…',self._waveform)]:
            button=wx.Button(advanced,label=label);button.Bind(wx.EVT_BUTTON,handler);actions.Add(button,0,wx.RIGHT|wx.BOTTOM,6);self.input_buttons.append(button)
        details.Add(actions,0,wx.ALL,8)
        self._fields_grid(advanced,details,[('mesh_step_mm','Maximum mesh step (mm)'),('air_padding_mm','Air boundary padding (mm)'),
                         ('max_cells','Maximum cells'),('convergence_tolerance','Convergence tolerance (fraction)'),
                         ('relative_permittivity','Permittivity for length check')])
        advanced.SetSizer(details);settings.Add(self.advanced,0,wx.EXPAND|wx.ALL,10)
        applicability=wx.StaticText(setup,label='Copper loss is included. Converter regulation, switching-device losses, insulation safety and thermal equilibrium are outside this model. Review the solver checks after running.')
        self.applicability=applicability;self._applicability_text=applicability.GetLabel()
        applicability.Wrap(1030);settings.Add(applicability,0,wx.EXPAND|wx.ALL,10)
        setup.SetSizer(settings);self.book.AddPage(setup,'1 · Set up loop')
        self._quick_stacked=None;setup.Bind(wx.EVT_SIZE,self._setup_layout)
        results = wx.Panel(self.book); result_layout = wx.BoxSizer(wx.VERTICAL)
        self.summary_values={};self.summary_notes={};cards=wx.WrapSizer(wx.HORIZONTAL)
        for key,title in [('total_loss_w','Total copper heat'),('ac_loss_w','Ripple heating'),('ripple_voltage_rms_v','AC loop drop'),('total_current_rms_a','DC + ripple RMS')]:
            panel=wx.Panel(results);panel.SetBackgroundColour('#eef5f7');box=wx.BoxSizer(wx.VERTICAL)
            box.Add(wx.StaticText(panel,label=title),0,wx.ALL,8)
            value=wx.StaticText(panel,label='—');font=value.GetFont().Bold();font.SetPointSize(max(14,font.GetPointSize()+4));value.SetFont(font);box.Add(value,0,wx.LEFT|wx.RIGHT,8)
            hint=wx.StaticText(panel,label='Run a study');box.Add(hint,0,wx.ALL,8)
            panel.SetMinSize((220,-1));panel.SetSizer(box);cards.Add(panel,0,wx.RIGHT|wx.BOTTOM,8)
            self.summary_values[key]=value;self.summary_notes[key]=hint
        result_layout.Add(cards,0,wx.EXPAND|wx.ALL,8)
        self.result_summary = wx.StaticText(results,label='No AC result yet.')
        result_layout.Add(self.result_summary,0,wx.EXPAND|wx.ALL,8)
        chart_row=wx.BoxSizer(wx.HORIZONTAL)
        chart_row.Add(wx.StaticText(results,label='Inspect'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
        self.plot_view=wx.Choice(results,choices=['Copper and return path','Resistance and reactance','Heating by harmonic'])
        self.plot_view.SetSelection(2);self.plot_view.Bind(wx.EVT_CHOICE,self._chart_changed)
        chart_row.Add(self.plot_view,0,wx.RIGHT,12)
        chart_row.Add(wx.StaticText(results,label='One large plot · select table rows or click the plot to inspect.'),0,wx.ALIGN_CENTER_VERTICAL)
        result_layout.Add(chart_row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,8)
        self.result_split=wx.SplitterWindow(results,style=wx.SP_LIVE_UPDATE|wx.SP_3D)
        plots=wx.Panel(self.result_split);plot_layout=wx.BoxSizer(wx.VERTICAL)
        self.figure = Figure(figsize=(11, 5)); Canvas, Toolbar = canvas_types
        self.canvas = Canvas(plots, wx.ID_ANY, self.figure); toolbar = Toolbar(self.canvas); toolbar.Realize()
        plot_layout.Add(self.canvas, 1, wx.EXPAND); plot_layout.Add(toolbar, 0, wx.EXPAND);plots.SetSizer(plot_layout)
        self.result_tables = wx.Notebook(self.result_split)
        self.table = wx.ListCtrl(self.result_tables, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate([('Frequency (kHz)',150),('Resistance (mΩ)',155),('Reactance (mΩ)',155),('Ripple RMS (A)',150),('Copper heat (mW)',170)]):
            self.table.InsertColumn(index, label, width=width)
        self.table.SetMinSize((-1, 150)); self.table.SetToolTip('Select a harmonic to highlight its plot point. Columns are resizable.')
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self._table_selected)
        self.result_tables.AddPage(self.table,'Harmonics')
        self.conductor_table = wx.ListCtrl(self.result_tables,style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index,(label,width) in enumerate([('Conductor / return',230),('DC heat (mW)',150),('Ripple heat (mW)',155),('Total heat (mW)',155)]):
            self.conductor_table.InsertColumn(index,label,width=width)
        self.conductor_table.Bind(wx.EVT_LIST_ITEM_SELECTED,self._conductor_selected)
        self.result_tables.AddPage(self.conductor_table,'Conductors')
        self.result_tables.SetMinSize((-1,170))
        self.result_split.SplitHorizontally(plots,self.result_tables,-175);self.result_split.SetMinimumPaneSize(120);self.result_split.SetSashGravity(.8)
        result_layout.Add(self.result_split, 1, wx.EXPAND | wx.ALL, 8); results.SetSizer(result_layout)
        self.book.AddPage(results, '2 · Heating & drop')
        self.details = wx.TextCtrl(self.book, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.book.AddPage(self.details, '3 · Solver checks')
        root.Add(self.book, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.status = wx.StaticText(self, label='Illustrative loop shown. Enter your actual copper geometry, '
                                  'return path and operating currents before running.')
        self.status.Wrap(1080); root.Add(self.status, 0, wx.EXPAND | wx.ALL, 10)
        footer = wx.BoxSizer(wx.HORIZONTAL)
        self.run = wx.Button(self, label='Run AC / ripple losses'); self.stop = wx.Button(self, label='Cancel')
        self.export = wx.Button(self, label='Export HTML / JSON…'); close = wx.Button(self, wx.ID_CLOSE, label='Close')
        for control in (self.run, self.stop, self.export, close): footer.Add(control, 0, wx.RIGHT, 8)
        root.Add(footer, 0, wx.ALIGN_RIGHT | wx.ALL, 10); self.SetSizer(root)
        self.run.Bind(wx.EVT_BUTTON, self._run); self.stop.Bind(wx.EVT_BUTTON, lambda e:self._cancel.set())
        self.run.SetDefault()
        self.export.Bind(wx.EVT_BUTTON, self._export); close.Bind(wx.EVT_BUTTON, self._close)
        self.Bind(wx.EVT_CLOSE, self._close); self.stop.Disable(); self.export.Disable()
        self.canvas.mpl_connect('motion_notify_event', self._hover)
        self.canvas.mpl_connect('button_press_event', self._plot_selected)
        self._load_controls(self.model)
        self._preview_timer.Stop();self._preview_loop()

    def _fields_grid(self,parent,layout,definitions):
        grid=wx.FlexGridSizer(cols=4,hgap=8,vgap=8);grid.AddGrowableCol(1);grid.AddGrowableCol(3)
        for key,label in definitions:
            grid.Add(wx.StaticText(parent,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(parent,value=str(self.model[key]),size=(110,-1))
            control.SetToolTip(label+'. Explicit model input, not a board measurement.')
            if key=='convergence_tolerance':control.SetToolTip('Allowed refinement change as a fraction: 0.05 means 5%.')
            self.fields[key]=control;grid.Add(control,0,wx.EXPAND);control.Bind(wx.EVT_TEXT,self._changed)
        layout.Add(grid,0,wx.EXPAND|wx.ALL,10)

    def _setup_layout(self,event=None):
        setup=self.book.GetPage(0);width=max(400,setup.GetClientSize().width)
        stacked=width<1000
        if stacked!=self._quick_stacked:
            self._quick_stacked=stacked
            self.quick_body.SetOrientation(wx.VERTICAL if stacked else wx.HORIZONTAL)
            for control,text in ((self.quick_note,self._quick_note_text),(self.applicability,self._applicability_text)):
                control.SetLabel(text);control.Wrap(max(350,width-70))
            setup.Layout();setup.FitInside()
        if event:event.Skip()

    def _mode_changed(self,event=None):
        if self._loading:return
        custom=self.setup_mode.GetSelection()==1
        self._quick_dirty=not custom
        if not custom:self.input_path=None;self.input_sha=None
        if custom:self.advanced.Collapse(False)
        self._invalidate();self._schedule_preview()
        self.status.SetLabel('Custom tables are used by Run.' if custom else 'Run applies the visible quick-loop dimensions and ripple current.')
        self.book.GetPage(0).Layout();self.book.GetPage(0).FitInside()

    def _quick_changed(self,event=None):
        if not self._loading:
            self.setup_mode.SetSelection(0);self._quick_dirty=True;self._invalidate();self._schedule_preview()
            self.input_path=None;self.input_sha=None
            self.status.SetLabel('Quick inputs changed. Run applies this loop and updates the results.')
        if event:event.Skip()

    def _schedule_preview(self):
        if self._preview_timer:self._preview_timer.Stop()
        self._preview_timer=wx.CallLater(140,self._preview_loop)

    def _preview_loop(self):
        if self._closed:return
        from matplotlib.patches import Rectangle
        self.preview_figure.clear();axis=self.preview_figure.add_subplot(111)
        try:
            if self.setup_mode.GetSelection()==0:
                from .ac_setup import quick_loop
                rows=quick_loop(self.model,self.quick_preset.GetStringSelection(),**{key:control.GetValue() for key,control in self.quick_fields.items()})['conductors']
            else:
                rows=[dict(name=self.conductors.GetCellValue(i,0),**{key:float(self.conductors.GetCellValue(i,j)) for j,key in enumerate(('x_mm','y_mm','width_mm','thickness_mm','current_scale'),1)}) for i in range(self.conductors.GetNumberRows())]
            if (not rows or any(not math.isfinite(row[key]) for row in rows for key in ('x_mm','y_mm','width_mm','thickness_mm','current_scale')) or
                any(row[key]<=0 for row in rows for key in ('width_mm','thickness_mm'))):raise ValueError('Enter finite, positive dimensions.')
            for row in rows:
                color='#d27826' if row['current_scale']>0 else '#176aa0' if row['current_scale']<0 else '#70818a'
                axis.add_patch(Rectangle((row['x_mm']-row['width_mm']/2,row['y_mm']-row['thickness_mm']/2),row['width_mm'],row['thickness_mm'],facecolor=color,edgecolor='#253d49'))
                axis.annotate(row['name']+' · current ×'+format(row['current_scale'],'.3g'),(row['x_mm'],row['y_mm']+row['thickness_mm']/2),xytext=(0,7),textcoords='offset points',ha='center',fontsize=9)
            axis.autoscale_view();axis.margins(.2,.3);axis.set_aspect('equal',adjustable='box')
            axis.set_xlabel('Cross-section x (mm)',fontsize=9);axis.set_ylabel('y (mm)',fontsize=9);axis.tick_params(labelsize=8)
            axis.set_title('Loop preview · colour indicates current direction',fontsize=10)
        except (ValueError,TypeError,KeyError,OverflowError):
            axis.text(.5,.5,'Enter valid loop dimensions to preview.',ha='center',va='center',transform=axis.transAxes);axis.set_axis_off()
        self.preview_figure.tight_layout();self.preview_canvas.draw_idle()

    def _quick_controls(self, parent, layout):
        from .ac_setup import PRESETS
        group=wx.StaticBoxSizer(wx.VERTICAL,parent,'Quick loop · explicit dimensions and RMS ripple')
        parent=group.GetStaticBox()
        self.quick_preset=wx.Choice(parent,choices=list(PRESETS));self.quick_preset.SetSelection(0)
        self.quick_preset.Bind(wx.EVT_CHOICE,self._quick_changed)
        group.Add(self.quick_preset,0,wx.EXPAND|wx.ALL,6)
        body=wx.BoxSizer(wx.HORIZONTAL);self.quick_body=body
        fields=wx.FlexGridSizer(cols=2,hgap=7,vgap=7);fields.AddGrowableCol(1)
        self.quick_fields={}
        for key,label,value in [('width_mm','Copper width mm','2'),('thickness_mm','Copper thickness mm','.07'),
                                ('gap_mm','Surface gap to return mm','.73'),('frequency_khz','Ripple frequency kHz','100'),
                                ('ripple_rms_a','Ripple RMS A','1')]:
            fields.Add(wx.StaticText(parent,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(parent,value=value);self.quick_fields[key]=control;fields.Add(control,1,wx.EXPAND)
            control.SetToolTip({'width_mm':'Copper width in the cross-section, not the conductor length.',
                'thickness_mm':'Actual copper thickness: 0.035 mm is 35 µm. This is not the PCB thickness.',
                'gap_mm':'Copper surface-to-surface gap, not centre spacing.',
                'frequency_khz':'One supplied ripple frequency. Use Custom loop for an SMPS harmonic spectrum.',
                'ripple_rms_a':'AC ripple RMS current only. For peak-to-peak triangular ripple, use the custom waveform builder.'}[key])
            self.input_buttons.append(control)
            control.Bind(wx.EVT_TEXT,self._quick_changed)
        body.Add(fields,1,wx.EXPAND|wx.ALL,6)
        self.preview_figure=Figure(figsize=(7,2.2),dpi=90)
        self.preview_canvas=self._canvas_type(parent,wx.ID_ANY,self.preview_figure);self.preview_canvas.SetMinSize((-1,205))
        body.Add(self.preview_canvas,1,wx.EXPAND|wx.ALL,6)
        group.Add(body,0,wx.EXPAND)
        note=wx.StaticText(parent,label='Uses the length, DC current and rail voltage above. Run applies the visible quick recipe; '
                           'it does not extract a PCB return or converter waveform. Split returns explicitly carry half the return current each.')
        self.quick_note=note;self._quick_note_text=note.GetLabel()
        note.Wrap(980);group.Add(note,0,wx.EXPAND|wx.ALL,6)
        buttons=wx.WrapSizer(wx.HORIZONTAL)
        button=wx.Button(parent,label='Review recipe in custom table')
        button.Bind(wx.EVT_BUTTON,self._review_quick);buttons.Add(button,0,wx.RIGHT,7);self.input_buttons.append(button)
        help_button=wx.Button(parent,label='AC model help');help_button.Bind(wx.EVT_BUTTON,self._quick_help)
        buttons.Add(help_button,0,wx.RIGHT,7);self.input_buttons.append(help_button)
        self.input_buttons.append(self.quick_preset)
        group.Add(buttons,0,wx.ALL,6);layout.Add(group,0,wx.EXPAND|wx.ALL,10)

    def _quick_help(self,event=None):
        from wayricad_runtime.help import open_help
        open_help(self,Path(__file__).with_name('ac_setup_help.html'))

    def _review_quick(self,event=None):
        if self._apply_quick():
            self.setup_mode.SetSelection(1);self.advanced.Collapse(False)
            self.book.GetPage(0).Layout();self.book.GetPage(0).FitInside()

    def _apply_quick(self, run=False):
        if self._busy:return
        try:
            from .ac_setup import quick_loop
            study=quick_loop(self._study(),self.quick_preset.GetStringSelection(),
                            **{key:control.GetValue() for key,control in self.quick_fields.items()})
            self._load_controls(study);self.setup_mode.SetSelection(0);self._quick_dirty=False;self._invalidate();self._schedule_preview()
            self.input_path=None;self.input_sha=None
            self.status.SetLabel('Explicit loop prepared. Check outgoing/return geometry and RMS ripple; no board extraction was assumed.')
            if run:self._run()
            return True
        except (ValueError,TypeError,KeyError) as exc:self.status.SetLabel(str(exc));return False

    def _grid(self, parent, headings):
        grid = wx.grid.Grid(parent); grid.CreateGrid(0, len(headings)); grid.SetRowLabelSize(35)
        for index, label in enumerate(headings):
            grid.SetColLabelValue(index, label); grid.SetColSize(index, 175 if index == 0 else 145)
        grid.SetMinSize((-1, 150)); grid.SetDefaultRowSize(28)
        grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self._changed)
        return grid

    def _load_controls(self, study):
        # Validate the editable structure before changing any visible control.
        # A malformed import must not leave an old result beside partial inputs.
        prepared = []
        for key, keys in [('conductors',('name','x_mm','y_mm','width_mm','thickness_mm','current_scale')),
                          ('harmonics',('frequency_hz','current_rms_a'))]:
            rows = study[key]
            if not isinstance(rows,list) or len(rows) > (32 if key == 'harmonics' else 16):
                raise ValueError('AC conductor/harmonic table exceeds its supported size.')
            prepared.append([[str(row[name]) for name in keys] for row in rows])
        self._loading = True
        try:
            self.model = copy.deepcopy(study)
            for key, control in self.fields.items(): control.ChangeValue(str(study.get(key, initial_study()[key])))
            for grid, rows in zip((self.conductors,self.harmonics),prepared):
                if grid.GetNumberRows(): grid.DeleteRows(0, grid.GetNumberRows())
                if rows: grid.AppendRows(len(rows))
                for index, row in enumerate(rows):
                    for column, value in enumerate(row): grid.SetCellValue(index, column, value)
        finally: self._loading = False
        self._quick_dirty=False
        self._schedule_preview()

    def _study(self):
        for grid in (self.conductors,self.harmonics):
            if grid.IsCellEditControlEnabled(): grid.SaveEditControlValue(); grid.DisableCellEditControl()
        study = copy.deepcopy(self.model)
        for key, control in self.fields.items():
            value = float(control.GetValue())
            if not math.isfinite(value): raise ValueError('All AC model inputs must be finite.')
            if key == 'max_cells':
                if value != int(value): raise ValueError('Cell budget must be a whole number.')
                value = int(value)
            study[key] = value
        study['conductors'] = []
        for index in range(self.conductors.GetNumberRows()):
            row = {'name': self.conductors.GetCellValue(index,0).strip()}
            for column,key in enumerate(('x_mm','y_mm','width_mm','thickness_mm','current_scale'),1):
                row[key] = float(self.conductors.GetCellValue(index,column))
            study['conductors'].append(row)
        study['harmonics'] = [{'frequency_hz':float(self.harmonics.GetCellValue(index,0)),
                                'current_rms_a':float(self.harmonics.GetCellValue(index,1))}
                               for index in range(self.harmonics.GetNumberRows())]
        return parse_study(json.dumps(study, allow_nan=False).encode('utf-8'))

    def _invalidate(self):
        self.result = None; self.export.Disable(); self.table.DeleteAllItems(); self.conductor_table.DeleteAllItems()
        self.figure.clear(); self.canvas.draw_idle(); self.details.ChangeValue(''); self._focus = None
        self.result_summary.SetLabel('No current AC result.');self._cell_lookup = {};self._cell_left = [];self._cell_bottom = []
        for value in self.summary_values.values():value.SetLabel('—')
        for value in self.summary_notes.values():value.SetLabel('Run a study')

    def _changed(self, event=None):
        if not self._loading:
            if not event or event.GetEventObject() in (self.harmonics,self.fields['dc_current_a']):
                self.model.pop('waveform',None)
            self.input_path = None; self.input_sha = None; self._invalidate()
            if not event or event.GetEventObject() in (self.conductors,self.harmonics):
                self.setup_mode.SetSelection(1);self._quick_dirty=False
            self._schedule_preview()
            self.status.SetLabel('Inputs changed. Run again to update the AC results.')
        if event: event.Skip()

    def _add(self, grid):
        grid.AppendRows(1); index = grid.GetNumberRows()-1
        defaults = ['Conductor '+str(index+1),'0','0','1','.035','0'] if grid is self.conductors else ['100000','1']
        for column,value in enumerate(defaults): grid.SetCellValue(index,column,value)
        self._changed()

    def _remove(self, grid):
        index = grid.GetGridCursorRow()
        if 0 <= index < grid.GetNumberRows(): grid.DeleteRows(index,1); self._changed()

    def _waveform(self,event=None):
        dialog = wx.Dialog(self,title='Build SMPS current spectrum',size=(600,480),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        root = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(dialog,label='Triangular output ripple uses peak-to-peak amplitude plus the DC mean. '
                             'Pulsed input current uses the ON current and duty cycle. '
                             'A finite harmonic band does not model edge rise time or the converter itself.')
        note.Wrap(550);root.Add(note,0,wx.EXPAND|wx.ALL,12)
        kind = wx.Choice(dialog,choices=['Triangular output ripple','Pulsed input current']);kind.SetSelection(0)
        root.Add(kind,0,wx.EXPAND|wx.LEFT|wx.RIGHT,12)
        grid = wx.FlexGridSizer(cols=2,hgap=8,vgap=10);grid.AddGrowableCol(1)
        controls = {}
        for key,label,default in [('frequency_hz','Switching frequency (Hz)','100000'),
                                  ('amplitude_a','Ripple peak-to-peak / pulse ON current (A)','2'),
                                  ('dc_current_a','DC mean for triangular ripple (A)',self.fields['dc_current_a'].GetValue()),
                                  ('duty','Pulse duty cycle (0–1)','0.5'),
                                  ('terms','Highest harmonic order (1–32)','8')]:
            grid.Add(wx.StaticText(dialog,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            controls[key] = wx.TextCtrl(dialog,value=default);grid.Add(controls[key],1,wx.EXPAND)
        root.Add(grid,1,wx.EXPAND|wx.ALL,12);root.Add(dialog.CreateButtonSizer(wx.OK|wx.CANCEL),0,wx.ALIGN_RIGHT|wx.ALL,12)
        dialog.SetSizer(root)
        try:
            if dialog.ShowModal() != wx.ID_OK:return
            from .ac_analysis import waveform_harmonics
            config = {key:float(control.GetValue()) for key,control in controls.items()}
            if config['terms'] != int(config['terms']):raise ValueError('Highest harmonic order must be a whole number.')
            config['terms'] = int(config['terms']);config['kind'] = 'triangle' if kind.GetSelection()==0 else 'pulse'
            generated = waveform_harmonics(**config)
            study = self._study();study['dc_current_a'] = generated['dc_current_a'];study['harmonics'] = generated['harmonics']
            self._load_controls(study);self._changed();self.model['waveform'] = config
            self.status.SetLabel(str(generated.get('notice','Finite harmonic band generated.'))+
                                 ' Omitted AC RMS: '+self._value(generated.get('omitted_rms_a'))+' A. Review before running.')
        except (ValueError,TypeError,KeyError) as exc:self.status.SetLabel(str(exc))
        finally:dialog.Destroy()

    def _load(self, event=None):
        with wx.FileDialog(self, 'Load AC study', defaultDir=project_directory(self), wildcard='JSON study (*.json)|*.json', style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = dialog.GetPath()
        try:
            study,digest = load_study(path); self._load_controls(study); self._invalidate()
            self.setup_mode.SetSelection(1);self.advanced.Collapse(False);self._schedule_preview()
            self.book.GetPage(0).Layout();self.book.GetPage(0).FitInside()
            self.input_path = path; self.input_sha = digest; self.status.SetLabel('Loaded custom model. Review geometry and RMS currents before running.')
        except (ValueError,OSError,KeyError,TypeError) as exc: self.status.SetLabel(str(exc))

    def _save(self, event=None):
        if self._quick_dirty and not self._apply_quick():return
        try: study = self._study()
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc)); return
        with wx.FileDialog(self, 'Save AC inputs', defaultDir=project_directory(self), defaultFile='ac-copper-study.json', wildcard='JSON (*.json)|*.json', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = Path(dialog.GetPath())
        try:
            protect_outputs([path], [self.board_path] if self.board_path else [])
            path.write_text(json.dumps(study,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            self.status.SetLabel('Saved explicit model inputs.')
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc))

    def _run(self, event=None):
        if self._busy: return
        if self.setup_mode.GetSelection()==0 and self._quick_dirty and not self._apply_quick():return
        try: request = {'action':'ac','study':self._study()}
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc)); return
        if self.board_path: request.update(board_path=self.board_path,source_sha256=self.sha)
        if self.input_path: request.update(study_input_path=self.input_path,study_file_sha256=self.input_sha)
        self._invalidate(); self._busy = True; self._cancel.clear(); self.run.Disable(); self.stop.Enable()
        for control in list(self.fields.values()) + [self.conductors,self.harmonics] + self.input_buttons: control.Disable()
        self.status.SetLabel('Solving skin/proximity fields and mesh/boundary checks. Cancel discards partial results.')
        def work():
            result = None; error = None
            try: result = self.runner(copy.deepcopy(request), self._cancel.is_set)
            except Exception as exc: error = str(exc)
            if not self._closed: wx.CallAfter(self._finished,result,error)
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, result, error):
        self._busy = False
        if self._closed: return
        self.run.Enable(); self.stop.Disable()
        for control in list(self.fields.values()) + [self.conductors,self.harmonics] + self.input_buttons: control.Enable()
        if self._closing: self._finish_close(); return
        if self._cancel.is_set(): error = 'AC study cancelled. No partial result accepted.'
        if not error and (not isinstance(result,dict) or 'ac' not in result): error = 'Worker returned no AC result.'
        if error: self.status.SetLabel(error); return
        self.result = result; self._draw_result()
        ac=result['ac'];units={'total_loss_w':'W','ac_loss_w':'W','ripple_voltage_rms_v':'V','total_current_rms_a':'A'}
        for key,value in self.summary_values.items():value.SetLabel(engineering(ac.get(key),units[key]))
        count=len(ac.get('harmonics',[]))
        notes={'total_loss_w':'DC '+engineering(ac.get('dc_loss_w'),'W')+' + ripple',
               'ac_loss_w':str(count)+' supplied '+('frequency' if count==1 else 'frequencies'),
               'ripple_voltage_rms_v':'Copper-loop RMS voltage',
               'total_current_rms_a':'DC and supplied ripple combined'}
        for key,value in self.summary_notes.items():value.SetLabel(notes[key])
        self.result_summary.SetLabel(str(ac.get('status','UNKNOWN'))+' · Copper model only. Select a harmonic or conductor for details.')
        self.result_summary.SetForegroundColour('#203744' if ac.get('status')=='CONVERGED' else '#9b3d24')
        self.result_summary.Wrap(max(600,self.GetClientSize().width-40));self.book.GetPage(1).Layout()
        self._cell_lookup = {(cell['x_mm']-cell['width_mm']/2,cell['y_mm']-cell['height_mm']/2):cell for cell in result['ac'].get('cells',[])}
        self._cell_left = sorted({key[0] for key in self._cell_lookup});self._cell_bottom = sorted({key[1] for key in self._cell_lookup})
        self.details.ChangeValue(summary(result)); self.export.Enable(); self.book.SetSelection(1)
        for index,row in enumerate(result['ac'].get('harmonics',[])):
            values = [None if row.get(key) is None else row[key]*scale for key,scale in [('frequency_hz',.001),('resistance_ohm',1000),('reactance_ohm',1000),('current_rms_a',1),('loss_w',1000)]]
            self.table.InsertItem(index,self._value(values[0]))
            for column,value in enumerate(values[1:],1): self.table.SetItem(index,column,self._value(value))
            self.table.SetItemData(index,index)
        for index,row in enumerate(result['ac'].get('conductors',[])):
            self.conductor_table.InsertItem(index,row['name'])
            for column,key in enumerate(('dc_loss_w','ac_loss_w','total_loss_w'),1):
                self.conductor_table.SetItem(index,column,self._value(None if row.get(key) is None else row[key]*1000))
        self.status.SetLabel(str(result['ac'].get('status','Unknown'))+' · Review the mesh, boundary and applicability checks. Hover / click plots for details.')

    @staticmethod
    def _value(value): return 'Unknown' if value is None else format(value,'.5g') if isinstance(value,(int,float)) else str(value)

    def _draw_result(self):
        if not self.result:return
        self._focus=None
        draw(self.figure,self.result,view=('geometry','impedance','losses')[max(0,self.plot_view.GetSelection())])
        self.canvas.draw_idle()

    def _chart_changed(self,event=None):
        self._draw_result()
        selected=self.table.GetFirstSelected()
        if self.plot_view.GetSelection()!=0 and selected>=0:self._select_harmonic(selected)

    def _harmonic_at(self,event):
        if not self.result or event.xdata is None or event.inaxes not in self.figure.axes[1:3]: return None
        if event.xdata <= 0: return None
        rows = self.result['ac'].get('harmonics',[])
        return min(range(len(rows)), key=lambda i:abs(math.log(rows[i]['frequency_hz']/event.xdata))) if rows else None

    def _hover(self,event):
        if self.result and event.inaxes == self.figure.axes[0] and event.xdata is not None and event.ydata is not None:
            ix = bisect_right(self._cell_left,event.xdata)-1;iy = bisect_right(self._cell_bottom,event.ydata)-1
            if ix >= 0 and iy >= 0:
                cell = self._cell_lookup.get((self._cell_left[ix],self._cell_bottom[iy]))
            else:cell = None
            if cell:
                if abs(event.xdata-cell['x_mm']) <= cell['width_mm']/2 and abs(event.ydata-cell['y_mm']) <= cell['height_mm']/2:
                    self.status.SetLabel(cell['conductor']+' · RMS J '+self._value(cell['current_density_rms_a_mm2'])+
                                         ' A/mm² · Joule loss density '+self._value(cell['loss_density_w_mm3'])+' W/mm³')
                    return
        index = self._harmonic_at(event)
        if index is None: return
        row = self.result['ac']['harmonics'][index]
        self.status.SetLabel(' · '.join(label+engineering(row.get(key),unit) for key,label,unit in
                             [('frequency_hz','Ripple ','Hz'),('current_rms_a','RMS ','A'),('resistance_ohm','R ','Ω'),('reactance_ohm','X ','Ω'),('loss_w','Heat ','W')]))

    def _select_harmonic(self,index):
        if not self.result: return
        row = self.result['ac']['harmonics'][index]
        if self._focus:
            for artist in self._focus: artist.remove()
        self._focus = [axis.axvline(row['frequency_hz'],color='#d85e20',linestyle='--',alpha=.8) for axis in self.figure.axes[1:3]]
        self.canvas.draw_idle()
        if not self.table.IsSelected(index): self.table.Select(index)
        self.table.EnsureVisible(index)

    def _table_selected(self,event):
        if self.plot_view.GetSelection()==0:self.plot_view.SetSelection(1);self._draw_result()
        self._select_harmonic(event.GetIndex())

    def _select_conductor(self,index):
        if not self.result:return
        if self.plot_view.GetSelection()!=0:self.plot_view.SetSelection(0);self._draw_result()
        row = self.result['study']['conductors'][index]; axis = self.figure.axes[0]
        for patch in axis.patches:
            selected = patch.get_label() == row['name']
            patch.set_edgecolor('#e35717' if selected else '#20323b'); patch.set_linewidth(2.5 if selected else .8)
        self.canvas.draw_idle(); self.result_tables.SetSelection(1)
        if not self.conductor_table.IsSelected(index):self.conductor_table.Select(index)
        self.conductor_table.EnsureVisible(index)

    def _conductor_selected(self,event):self._select_conductor(event.GetIndex())

    def _plot_selected(self,event):
        if event.button != 1: return
        if self.result and event.inaxes == self.figure.axes[0] and event.xdata is not None and event.ydata is not None:
            for index,row in enumerate(self.result['study']['conductors']):
                if abs(event.xdata-row['x_mm']) <= row['width_mm']/2 and abs(event.ydata-row['y_mm']) <= row['thickness_mm']/2:
                    self._select_conductor(index);return
        index = self._harmonic_at(event)
        if index is not None: self._select_harmonic(index)

    def _export(self,event=None):
        if not self.result: return
        with wx.FileDialog(self,'Export AC evidence',defaultFile='ac-copper.html',wildcard='HTML (*.html)|*.html',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = dialog.GetPath()
        if Path(path).with_suffix('.json').exists() and wx.MessageBox('Replace the existing paired JSON report?','Paired report exists',wx.YES_NO|wx.NO_DEFAULT,self) != wx.YES: return
        try: write_report(path,self.result); self.status.SetLabel('Exported '+path)
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc))

    def _close(self,event=None):
        if self._busy:
            self._closing = True; self._cancel.set(); self.status.SetLabel('Cancelling the worker before closing…')
            if event and hasattr(event,'CanVeto') and event.CanVeto(): event.Veto()
            return
        self._finish_close()

    def _finish_close(self):
        self._closed = True
        if self._preview_timer:self._preview_timer.Stop()
        if self.IsModal(): self.EndModal(wx.ID_CLOSE)
        else: self.Destroy()
