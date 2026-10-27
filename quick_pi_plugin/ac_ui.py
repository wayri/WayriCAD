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
from .ac_report import draw, summary, write_report


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
        note = wx.StaticText(self, label='1  Define straight conductors and explicit returns.  '
            '2  Enter DC and RMS ripple harmonics.  3  Run and review convergence.\n'
            'Skin/proximity and Joule losses are solved at a fixed copper temperature. '
            'This is an explicit cross-section model; saved-board geometry is not imported automatically.')
        note.Wrap(1080); root.Add(note, 0, wx.EXPAND | wx.ALL, 10)
        self.book = wx.Notebook(self); setup = wx.ScrolledWindow(self.book)
        setup.SetScrollRate(10, 10); settings = wx.BoxSizer(wx.VERTICAL)
        fields = wx.FlexGridSizer(cols=4, hgap=8, vgap=8)
        fields.AddGrowableCol(1);fields.AddGrowableCol(3)
        self.fields = {}
        definitions = [('length_mm','Length (mm)'),('reference_voltage_v','DC rail voltage (V)'),
                       ('dc_current_a','DC current (A)'),('temperature_c','Copper temperature (°C)'),
                       ('mesh_step_mm','Maximum mesh step (mm)'),('air_padding_mm','Air padding (mm)'),
                       ('max_cells','Cell budget'),('convergence_tolerance','Convergence tolerance (fraction)'),
                       ('relative_permittivity','Permittivity for length check')]
        for key, label in definitions:
            fields.Add(wx.StaticText(setup, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control = wx.TextCtrl(setup, value=str(self.model[key]), size=(110, -1))
            control.SetToolTip(label+'. Values are explicit model inputs, not board measurements.')
            self.fields[key] = control; fields.Add(control, 0, wx.EXPAND)
            control.Bind(wx.EVT_TEXT, self._changed)
        settings.Add(fields, 0, wx.EXPAND | wx.ALL, 10)
        self.conductors = self._grid(setup, ['Conductor / return', 'Centre x (mm)', 'Centre y (mm)',
                                             'Width (mm)', 'Thickness (mm)', 'Current ×'])
        settings.Add(wx.StaticText(setup, label='Conductors: signed current multipliers must sum to zero. '
                     'Use zero for an unpowered shield. Coordinates are cross-section centres.'),
                     0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        settings.Add(self.conductors, 0, wx.EXPAND | wx.ALL, 10)
        self.harmonics = self._grid(setup, ['Frequency (Hz)', 'Loop current RMS (A)'])
        settings.Add(wx.StaticText(setup, label='Distinct harmonic frequencies: enter RMS current, '
                     'not peak or peak-to-peak ripple. The same signed conductor multipliers apply to every harmonic.'),
                     0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        settings.Add(self.harmonics, 0, wx.EXPAND | wx.ALL, 10)
        actions = wx.WrapSizer(wx.HORIZONTAL)
        self.input_buttons = []
        for label, handler in [('Add conductor',lambda e:self._add(self.conductors)),
                               ('Remove conductor',lambda e:self._remove(self.conductors)),
                               ('Add harmonic',lambda e:self._add(self.harmonics)),
                               ('Remove harmonic',lambda e:self._remove(self.harmonics)),
                               ('Build SMPS waveform…',self._waveform),
                               ('Load JSON…',self._load),('Save inputs…',self._save)]:
            button = wx.Button(setup, label=label); button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.RIGHT, 6); self.input_buttons.append(button)
        settings.Add(actions, 0, wx.ALL, 10)
        self._quick_controls(setup, settings)
        applicability = wx.StaticText(setup, label='HV/LV and high-current studies use the supplied voltage/current. '
            'Results do not establish creepage, clearance, dielectric stress, switching-device loss, EMI, '
            'converter regulation, magnetic-component loss or thermal equilibrium. '
            'The mesh and outer boundary must pass convergence checks; failed checks remain explicit.')
        applicability.Wrap(1030); settings.Add(applicability, 0, wx.EXPAND | wx.ALL, 10)
        setup.SetSizer(settings); self.book.AddPage(setup, '1 · Define AC loop')
        results = wx.Panel(self.book); result_layout = wx.BoxSizer(wx.VERTICAL)
        self.result_summary = wx.StaticText(results,label='No AC result yet.')
        result_layout.Add(self.result_summary,0,wx.EXPAND|wx.ALL,8)
        self.figure = Figure(figsize=(11, 5)); Canvas, Toolbar = canvas_types
        self.canvas = Canvas(results, wx.ID_ANY, self.figure); toolbar = Toolbar(self.canvas); toolbar.Realize()
        result_layout.Add(self.canvas, 1, wx.EXPAND); result_layout.Add(toolbar, 0, wx.EXPAND)
        self.result_tables = wx.Notebook(results)
        self.table = wx.ListCtrl(self.result_tables, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate([('Frequency (Hz)',150),('R (Ω)',130),('X (Ω)',130),('RMS current (A)',150),('Loss (W)',140)]):
            self.table.InsertColumn(index, label, width=width)
        self.table.SetMinSize((-1, 150)); self.table.SetToolTip('Select a harmonic to highlight its plot point. Columns are resizable.')
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self._table_selected)
        self.result_tables.AddPage(self.table,'Harmonics')
        self.conductor_table = wx.ListCtrl(self.result_tables,style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index,(label,width) in enumerate([('Conductor',220),('DC loss (W)',150),('AC loss (W)',150),('Total loss (W)',150)]):
            self.conductor_table.InsertColumn(index,label,width=width)
        self.conductor_table.Bind(wx.EVT_LIST_ITEM_SELECTED,self._conductor_selected)
        self.result_tables.AddPage(self.conductor_table,'Conductors')
        self.result_tables.SetMinSize((-1,170))
        result_layout.Add(self.result_tables, 0, wx.EXPAND | wx.ALL, 8); results.SetSizer(result_layout)
        self.book.AddPage(results, '2 · AC results')
        self.details = wx.TextCtrl(self.book, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.book.AddPage(self.details, '3 · Checks / applicability')
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
        self.export.Bind(wx.EVT_BUTTON, self._export); close.Bind(wx.EVT_BUTTON, self._close)
        self.Bind(wx.EVT_CLOSE, self._close); self.stop.Disable(); self.export.Disable()
        self.canvas.mpl_connect('motion_notify_event', self._hover)
        self.canvas.mpl_connect('button_press_event', self._plot_selected)
        self._load_controls(self.model)

    def _quick_controls(self, parent, layout):
        from .ac_setup import PRESETS
        group=wx.StaticBoxSizer(wx.VERTICAL,parent,'Quick loop · explicit dimensions and RMS ripple')
        parent=group.GetStaticBox()
        self.quick_preset=wx.Choice(parent,choices=list(PRESETS));self.quick_preset.SetSelection(0)
        group.Add(self.quick_preset,0,wx.EXPAND|wx.ALL,6)
        fields=wx.FlexGridSizer(cols=4,hgap=7,vgap=7);fields.AddGrowableCol(1);fields.AddGrowableCol(3)
        self.quick_fields={}
        for key,label,value in [('width_mm','Copper width mm','2'),('thickness_mm','Copper thickness mm','.07'),
                                ('gap_mm','Surface gap to return mm','.3'),('frequency_khz','Ripple frequency kHz','100'),
                                ('ripple_rms_a','Ripple RMS A','1')]:
            fields.Add(wx.StaticText(parent,label=label),0,wx.ALIGN_CENTER_VERTICAL)
            control=wx.TextCtrl(parent,value=value);self.quick_fields[key]=control;fields.Add(control,1,wx.EXPAND)
            self.input_buttons.append(control)
        group.Add(fields,0,wx.EXPAND|wx.ALL,6)
        note=wx.StaticText(parent,label='Uses the length, DC current and rail voltage in the detailed settings. This recipe replaces conductor/harmonic tables; '
                           'it does not extract a PCB return or converter waveform. Split returns explicitly carry half the return current each.')
        note.Wrap(980);group.Add(note,0,wx.EXPAND|wx.ALL,6)
        buttons=wx.WrapSizer(wx.HORIZONTAL)
        for label,run in [('Apply quick loop',False),('Apply quick loop and run',True)]:
            button=wx.Button(parent,label=label);button.Bind(wx.EVT_BUTTON,lambda event,run=run:self._apply_quick(run))
            buttons.Add(button,0,wx.RIGHT,7);self.input_buttons.append(button)
        help_button=wx.Button(parent,label='AC model help');help_button.Bind(wx.EVT_BUTTON,self._quick_help)
        buttons.Add(help_button,0,wx.RIGHT,7);self.input_buttons.append(help_button)
        self.input_buttons.append(self.quick_preset)
        group.Add(buttons,0,wx.ALL,6);layout.Insert(0,group,0,wx.EXPAND|wx.ALL,10)

    def _quick_help(self,event=None):
        from wayricad_runtime.help import open_help
        open_help(self,Path(__file__).with_name('ac_setup_help.html'))

    def _apply_quick(self, run=False):
        if self._busy:return
        try:
            from .ac_setup import quick_loop
            study=quick_loop(self._study(),self.quick_preset.GetStringSelection(),
                            **{key:control.GetValue() for key,control in self.quick_fields.items()})
            self._load_controls(study);self._changed()
            self.status.SetLabel('Explicit loop prepared. Check outgoing/return geometry and RMS ripple; no board extraction was assumed.')
            if run:self._run()
        except (ValueError,TypeError,KeyError) as exc:self.status.SetLabel(str(exc))

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

    def _changed(self, event=None):
        if not self._loading:
            if not event or event.GetEventObject() in (self.harmonics,self.fields['dc_current_a']):
                self.model.pop('waveform',None)
            self.input_path = None; self.input_sha = None; self._invalidate()
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
        with wx.FileDialog(self, 'Load AC study', wildcard='JSON study (*.json)|*.json', style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = dialog.GetPath()
        try:
            study,digest = load_study(path); self._load_controls(study); self._invalidate()
            self.input_path = path; self.input_sha = digest; self.status.SetLabel('Loaded explicit model. Review geometry and RMS currents before running.')
        except (ValueError,OSError,KeyError,TypeError) as exc: self.status.SetLabel(str(exc))

    def _save(self, event=None):
        try: study = self._study()
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc)); return
        with wx.FileDialog(self, 'Save AC inputs', defaultFile='ac-copper-study.json', wildcard='JSON (*.json)|*.json', style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            path = Path(dialog.GetPath())
        try:
            protect_outputs([path], [self.board_path] if self.board_path else [])
            path.write_text(json.dumps(study,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            self.status.SetLabel('Saved explicit model inputs.')
        except (ValueError,OSError) as exc: self.status.SetLabel(str(exc))

    def _run(self, event=None):
        if self._busy: return
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
        self.result = result; draw(self.figure,result); self.canvas.draw_idle()
        self.result_summary.SetLabel('Total copper Joule loss: '+self._value(result['ac'].get('total_loss_w'))+
            ' W · Copper-loop AC drop RMS: '+self._value(result['ac'].get('ripple_voltage_rms_v'))+
            ' V · Reference waveform RMS: '+self._value(result['ac'].get('total_current_rms_a'))+' A')
        self._cell_lookup = {(cell['x_mm']-cell['width_mm']/2,cell['y_mm']-cell['height_mm']/2):cell for cell in result['ac'].get('cells',[])}
        self._cell_left = sorted({key[0] for key in self._cell_lookup});self._cell_bottom = sorted({key[1] for key in self._cell_lookup})
        self.details.ChangeValue(summary(result)); self.export.Enable(); self.book.SetSelection(1)
        for index,row in enumerate(result['ac'].get('harmonics',[])):
            values = [row.get(key) for key in ('frequency_hz','resistance_ohm','reactance_ohm','current_rms_a','loss_w')]
            self.table.InsertItem(index,self._value(values[0]))
            for column,value in enumerate(values[1:],1): self.table.SetItem(index,column,self._value(value))
            self.table.SetItemData(index,index)
        for index,row in enumerate(result['ac'].get('conductors',[])):
            self.conductor_table.InsertItem(index,row['name'])
            for column,key in enumerate(('dc_loss_w','ac_loss_w','total_loss_w'),1):
                self.conductor_table.SetItem(index,column,self._value(row.get(key)))
        self.status.SetLabel(str(result['ac'].get('status','Unknown'))+' · Review the mesh, boundary and applicability checks. Hover / click plots for details.')

    @staticmethod
    def _value(value): return 'Unknown' if value is None else format(value,'.7g') if isinstance(value,(int,float)) else str(value)

    def _harmonic_at(self,event):
        if not self.result or event.xdata is None or event.inaxes not in self.figure.axes[1:]: return None
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
        self.status.SetLabel(' · '.join(label+': '+self._value(row.get(key)) for key,label in
                             [('frequency_hz','Hz'),('current_rms_a','RMS A'),('resistance_ohm','R Ω'),('reactance_ohm','X Ω'),('loss_w','Loss W')]))

    def _select_harmonic(self,index):
        if not self.result: return
        row = self.result['ac']['harmonics'][index]
        if self._focus:
            for artist in self._focus: artist.remove()
        self._focus = [axis.axvline(row['frequency_hz'],color='#d85e20',linestyle='--',alpha=.8) for axis in self.figure.axes[1:]]
        self.canvas.draw_idle()
        if not self.table.IsSelected(index): self.table.Select(index)
        self.table.EnsureVisible(index)

    def _table_selected(self,event): self._select_harmonic(event.GetIndex())

    def _select_conductor(self,index):
        if not self.result:return
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
        if self.IsModal(): self.EndModal(wx.ID_CLOSE)
        else: self.Destroy()
