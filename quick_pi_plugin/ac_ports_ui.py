"""Standalone guided wx boundary for explicit MQS two-port studies.

Importing this module does not import wx, matplotlib, NumPy or SciPy.
"""
from __future__ import annotations

import json
import hashlib

from .ac_ports import LatestRun, SCHEMA, validate_study


def example_study():
    """Editable illustrative section, not extracted PCB geometry."""
    return {'schema': SCHEMA, 'cross_section': {
        'length_mm': 10., 'temperature_c': 20., 'relative_permittivity': 4.2,
        'mesh_step_mm': .1, 'air_padding_mm': 1., 'max_cells': 20000,
        'convergence_tolerance': .05,
        'conductors': [{'name': name, 'x_mm': x, 'y_mm': y,
                        'width_mm': .4, 'thickness_mm': .1}
                       for name, x, y in [('A', -.4, .2), ('B', -.4, -.2),
                                          ('C', .4, .2), ('D', .4, -.2)]]},
        'ports': [{'name': 'P1', 'positive': 'A', 'negative': 'B'},
                  {'name': 'P2', 'positive': 'C', 'negative': 'D'}],
        'frequencies_hz': [100., 1000., 10000.]}


def create_frame(parent=None, study=None, *, result_only=None):
    """Create, but do not show, a frame. Caller owns the wx App and main loop."""
    import wx
    import wx.grid as grid
    from matplotlib.figure import Figure
    from .plot_canvas import FigureCanvasWxAgg

    initial = validate_study(study if study is not None else example_study())[0]

    class PortsFrame(wx.Frame):
        def __init__(self):
            area = wx.Display().GetClientArea()
            size = (min(1000, area.width), min(760, area.height))
            title='Quick PI - Planar PDN Impedance' if result_only else 'Quick PI - Explicit AC Two-Port'
            super().__init__(parent, title=title, size=size)
            self._result_only = result_only is not None
            self.SetMinSize((min(640, area.width), min(440, area.height)))
            self.result = None
            self._input_path = None
            self._input_sha = None
            self._reference_path = None
            self._reference_sha = None
            self.reference = None
            self.reference_label = 'Imported reference'
            self._probes = {}
            self.job = LatestRun(wx.CallAfter, self._receive)
            panel = wx.Panel(self)
            layout = wx.BoxSizer(wx.VERTICAL)
            self.tabs = wx.Notebook(panel)
            self.geometry = wx.ScrolledWindow(self.tabs)
            self.geometry.SetScrollRate(12, 12)
            self.ports_page = wx.ScrolledWindow(self.tabs)
            self.ports_page.SetScrollRate(12, 12)
            self.results_page = wx.Panel(self.tabs)
            self.tabs.AddPage(self.geometry, '1 Geometry')
            self.tabs.AddPage(self.ports_page, '2 Ports and Frequencies')
            self.tabs.AddPage(self.results_page, '3 Results')
            layout.Add(self.tabs, 1, wx.EXPAND | wx.ALL, 8)
            bar = wx.WrapSizer(wx.HORIZONTAL)
            self.status = wx.StaticText(panel, label='Explicit MQS cross-section; not full-board extraction.')
            self.status_text = self.status.GetLabel()
            layout.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
            for label, handler in [('Help', self._help), ('Load', self._load),
                                   ('Reference...', self._reference), ('Run', self._run),
                                   ('Cancel', self._cancel), ('Save Result', self._save)]:
                if self._result_only and label in ('Load','Run','Cancel'):continue
                button = wx.Button(panel, label=label)
                button.Bind(wx.EVT_BUTTON, handler)
                bar.Add(button, 0, wx.LEFT, 4)
                if label == 'Save Result':
                    self.save_button = button
                    button.Enable(False)
            layout.Add(bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
            panel.SetSizer(layout)
            outer = wx.BoxSizer(wx.VERTICAL)
            outer.Add(panel, 1, wx.EXPAND)
            self.SetSizer(outer)
            self._build_geometry(initial['cross_section'])
            self._build_ports(initial)
            self._build_results()
            if self._result_only:
                self.tabs.DeletePage(0);self.tabs.DeletePage(0)
                self._receive(result_only,None)
            self.Bind(wx.EVT_CLOSE, self._close)
            self.Bind(wx.EVT_SIZE, self._resize)
            self.Centre()

        def _build_geometry(self, section):
            box = wx.BoxSizer(wx.VERTICAL)
            form = wx.FlexGridSizer(cols=2, hgap=12, vgap=6)
            form.AddGrowableCol(1)
            self.fields = {}
            for key, label in [('length_mm', 'Length (mm)'), ('temperature_c', 'Copper temperature (degC)'),
                               ('relative_permittivity', 'Relative permittivity (size guard only)'),
                               ('mesh_step_mm', 'Mesh step (mm)'), ('air_padding_mm', 'Initial air padding (mm)'),
                               ('max_cells', 'Maximum cells per mesh'),
                               ('convergence_tolerance', 'Convergence relative tolerance')]:
                form.Add(wx.StaticText(self.geometry, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                control = wx.TextCtrl(self.geometry, value=str(section[key]))
                control.Bind(wx.EVT_TEXT, self._changed)
                self.fields[key] = control
                form.Add(control, 1, wx.EXPAND)
            box.Add(form, 0, wx.EXPAND | wx.ALL, 8)
            self.conductors = grid.Grid(self.geometry)
            self.conductors.CreateGrid(len(section['conductors']), 5)
            self.columns = ('name', 'x_mm', 'y_mm', 'width_mm', 'thickness_mm')
            for i, label in enumerate(('Name', 'Center X (mm)', 'Center Y (mm)', 'Width (mm)', 'Thickness (mm)')):
                self.conductors.SetColLabelValue(i, label)
                self.conductors.SetColSize(i, 125)
            for i, row in enumerate(section['conductors']):
                for j, key in enumerate(self.columns):
                    self.conductors.SetCellValue(i, j, str(row[key]))
            self.conductors.SetMinSize((450, 200))
            self.conductors.Bind(grid.EVT_GRID_CELL_CHANGED, self._geometry_changed)
            box.Add(self.conductors, 1, wx.EXPAND | wx.ALL, 8)
            row = wx.BoxSizer(wx.HORIZONTAL)
            for art, tip, handler in [(wx.ART_PLUS, 'Add conductor', self._add),
                                      (wx.ART_MINUS, 'Remove selected conductor', self._remove)]:
                button = wx.BitmapButton(self.geometry, bitmap=wx.ArtProvider.GetBitmap(art, wx.ART_BUTTON))
                button.SetToolTip(tip)
                button.Bind(wx.EVT_BUTTON, handler)
                row.Add(button, 0, wx.RIGHT, 6)
            box.Add(row, 0, wx.ALL, 8)
            self.geometry.SetSizer(box)

        def _build_ports(self, study):
            box = wx.BoxSizer(wx.VERTICAL)
            form = wx.FlexGridSizer(cols=3, hgap=8, vgap=8)
            for label in ('Port name', 'Positive conductor', 'Negative conductor'):
                form.Add(wx.StaticText(self.ports_page, label=label))
            self.port_controls = []
            names = [c['name'] for c in study['cross_section']['conductors']]
            for port in study['ports']:
                name = wx.TextCtrl(self.ports_page, value=port['name'])
                positive = wx.Choice(self.ports_page, choices=names)
                negative = wx.Choice(self.ports_page, choices=names)
                positive.SetStringSelection(port['positive'])
                negative.SetStringSelection(port['negative'])
                name.Bind(wx.EVT_TEXT, self._changed)
                for choice in (positive, negative):
                    choice.Bind(wx.EVT_CHOICE, self._changed)
                self.port_controls.append((name, positive, negative))
                for control in (name, positive, negative):
                    form.Add(control, 1, wx.EXPAND)
            for column in range(3):
                form.AddGrowableCol(column)
            box.Add(form, 0, wx.EXPAND | wx.ALL, 12)
            box.Add(wx.StaticText(self.ports_page, label='Frequencies (Hz, comma separated; maximum 32)'),
                    0, wx.LEFT | wx.TOP, 12)
            self.frequency_input = wx.TextCtrl(self.ports_page, value=', '.join(
                str(f) for f in study['frequencies_hz']), style=wx.TE_MULTILINE)
            self.frequency_input.SetMinSize((-1, 100))
            self.frequency_input.Bind(wx.EVT_TEXT, self._changed)
            box.Add(self.frequency_input, 0, wx.EXPAND | wx.ALL, 12)
            self.ports_page.SetSizer(box)

        def _build_results(self):
            box = wx.BoxSizer(wx.VERTICAL)
            self.table = grid.Grid(self.results_page)
            self.table.CreateGrid(0, 9)
            self.table.EnableEditing(False)
            self.table.Bind(grid.EVT_GRID_LABEL_LEFT_CLICK,self._sort_table)
            self._table_rows=[];self._table_sort=None
            self.table.SetColLabelValue(0, 'Frequency (Hz)')
            for index, name in enumerate(('Z11', 'Z12', 'Z21', 'Z22')):
                self.table.SetColLabelValue(1+2*index, name + ' Re (ohm)')
                self.table.SetColLabelValue(2+2*index, name + ' Im (ohm)')
            self.figure = Figure(figsize=(6, 3), layout='constrained')
            self.canvas = FigureCanvasWxAgg(self.results_page, -1, self.figure)
            self.table.SetMinSize((-1,self.FromDIP(145)))
            self.table.SetMaxSize((-1,self.FromDIP(145)))
            convention = wx.StaticText(self.results_page,
                label='Zij is the voltage at port i per ampere at port j. The other port has zero net current.')
            box.Add(convention, 0, wx.LEFT | wx.TOP, 6)
            box.Add(self.table, 0, wx.EXPAND | wx.ALL, 6)
            box.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 6)
            from .plot_canvas import NavigationToolbar2WxAgg
            self.navigation = NavigationToolbar2WxAgg(self.canvas)
            box.Add(self.navigation,0,wx.EXPAND)
            self.canvas.mpl_connect('motion_notify_event',self._hover)
            self.results_page.SetSizer(box)

        def _clear(self, message):
            self.result = None
            self._probes = {}
            self._table_rows=[];self._table_sort=None
            if hasattr(self,'canvas'):self.canvas.SetToolTip('')
            self.save_button.Enable(False)
            if hasattr(self, 'table'):
                if self.table.GetNumberRows():
                    self.table.DeleteRows(0, self.table.GetNumberRows())
                self._reset_plot()
                self.canvas.draw_idle()
            self._set_status(message)

        def _set_status(self, message):
            self.status_text = message
            self.status.SetLabel(message)
            self.status.Wrap(max(100, self.GetClientSize().width - 24))

        def _resize(self, event):
            self._set_status(self.status_text)
            event.Skip()

        def _reset_plot(self):
            # Matplotlib's clear path can reset log-axis limits through zero.
            for axis in self.figure.axes:
                axis.set_xscale('linear')
            self.figure.clear()

        def _changed(self, event):
            self.reference = None
            self._reference_path = None
            self._reference_sha = None
            self.job.invalidate()
            self._clear('Inputs changed; results cleared.')
            event.Skip()

        def _sync_names(self):
            names = [self.conductors.GetCellValue(i, 0) for i in range(self.conductors.GetNumberRows())]
            for _, positive, negative in self.port_controls:
                for control in (positive, negative):
                    selected = control.GetStringSelection()
                    control.Set(names)
                    control.SetStringSelection(selected)

        def _geometry_changed(self, event):
            self._sync_names()
            self._changed(event)

        def _add(self, event):
            if self.conductors.GetNumberRows() < 16:
                i = self.conductors.GetNumberRows()
                self.conductors.AppendRows(1)
                for j, value in enumerate(('Conductor' + str(i+1), str(i), '0', '.4', '.1')):
                    self.conductors.SetCellValue(i, j, value)
                self._sync_names()
                self._changed(event)

        def _remove(self, event):
            if self.conductors.GetNumberRows() > 2:
                self.conductors.DeleteRows(max(0, self.conductors.GetGridCursorRow()), 1)
                self._sync_names()
                self._changed(event)

        def _collect(self):
            self.conductors.SaveEditControlValue()
            self.conductors.DisableCellEditControl()
            section = {key: (int(control.GetValue()) if key == 'max_cells' else float(control.GetValue()))
                       for key, control in self.fields.items()}
            section['conductors'] = [{key: self.conductors.GetCellValue(i, j) if j == 0 else
                                       float(self.conductors.GetCellValue(i, j))
                                      for j, key in enumerate(self.columns)}
                                     for i in range(self.conductors.GetNumberRows())]
            study = {'schema': SCHEMA, 'cross_section': section,
                     'ports': [{'name': name.GetValue(), 'positive': positive.GetStringSelection(),
                                'negative': negative.GetStringSelection()}
                               for name, positive, negative in self.port_controls],
                     'frequencies_hz': [float(f.strip()) for f in self.frequency_input.GetValue().split(',')]}
            return validate_study(study)[0]

        def _run(self, event):
            try:
                self._assert_inputs()
                study = self._collect()
            except (ValueError, TypeError, OSError) as exc:
                self.job.invalidate()
                self._clear(str(exc))
                return
            self._clear('Solving; cancellation takes effect between sparse solves.')
            self.job.submit(study)

        def _cancel(self, event):
            self.job.invalidate()
            self._clear('Cancelled; waiting for any active sparse solve to return.')

        def _receive(self, result, error):
            if error is not None:
                self._clear(str(error))
                return
            try:self._assert_inputs()
            except (OSError,ValueError) as exc:
                self._clear(str(exc));return
            if self._input_path is not None:
                result=dict(result,study_input_path=str(self._input_path),study_file_sha256=self._input_sha)
            self.result = result
            self.save_button.Enable(True)
            self._set_status(result['status'] + (' - explicit mesh; convergence not established.'
                if result['status']=='MODELLED' else ' - numerical sensitivity only; see saved evidence.'))
            rows = result['frequencies']
            self._table_rows=list(rows);self._table_sort=None
            if self.table.GetNumberRows():self.table.DeleteRows(0,self.table.GetNumberRows())
            self.table.AppendRows(len(rows))
            self._reset_plot()
            self._fill_table(rows)
            from .impedance_plots import draw_magnitudes
            self._probes=draw_magnitudes(self.figure,result,self.reference,self.reference_label)
            self.canvas.draw_idle()
            self.tabs.SetSelection(self.tabs.GetPageCount()-1)

        def _fill_table(self,rows):
            for i, row in enumerate(rows):
                self.table.SetCellValue(i, 0, format(row['frequency_hz'], '.7g'))
                for k, entry in enumerate(v for matrix_row in row['z_ohm'] for v in matrix_row):
                    self.table.SetCellValue(i, 1+2*k, format(entry['real'], '.7g'))
                    self.table.SetCellValue(i, 2+2*k, format(entry['imag'], '.7g'))

        def _sort_table(self,event):
            column=event.GetCol()
            if column<0 or not self._table_rows:
                event.Skip();return
            descending=self._table_sort==(column,False)
            def key(row):
                if column==0:return row['frequency_hz']
                entry=(column-1)//2
                return row['z_ohm'][entry//2][entry%2]['real' if column%2 else 'imag']
            self._table_rows=sorted(self._table_rows,key=key,reverse=descending)
            self._table_sort=(column,descending)
            self._fill_table(self._table_rows)

        def _hover(self,event):
            from .impedance_plots import probe_text
            text=probe_text(self._probes,event.inaxes,event.xdata)
            self.canvas.SetToolTip(text)

        def _reference(self,event):
            if self.result is None:
                self._set_status('Run a study before loading reference samples.')
                return
            with wx.FileDialog(self,'Load actual impedance reference',wildcard='JSON (*.json)|*.json',
                               style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST) as picker:
                if picker.ShowModal()!=wx.ID_OK:return
                try:
                    from pathlib import Path
                    from .ac_cli import MAX_STUDY_BYTES,parse_study
                    from .impedance_plots import samples
                    path=Path(picker.GetPath())
                    if path.stat().st_size>MAX_STUDY_BYTES:raise ValueError('Reference exceeds 4 MiB.')
                    raw=path.read_bytes()
                    reference=parse_study(raw,schema='wayricad.impedance-reference/v1')
                    samples(reference)
                    self.reference=reference;self.reference_label=path.stem
                    self._reference_path=path.resolve();self._reference_sha=hashlib.sha256(raw).hexdigest()
                    self._receive(self.result,None)
                    self._set_status('Imported reference; differences use common sampled frequencies only.')
                except (ValueError,OSError) as exc:
                    self._set_status('Reference rejected: '+str(exc))

        def _load(self, event):
            with wx.FileDialog(self, 'Load Two-Port Study', wildcard='JSON files (*.json)|*.json',
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                try:
                    from pathlib import Path
                    from .ac_cli import MAX_STUDY_BYTES, parse_study
                    source = Path(dialog.GetPath()).resolve()
                    if source.stat().st_size > MAX_STUDY_BYTES:
                        raise ValueError('Study exceeds 4 MiB.')
                    raw=source.read_bytes()
                    study = parse_study(raw, schema=SCHEMA)
                    normalized = validate_study(study)[0]
                    replacement = create_frame(parent, normalized)
                    replacement._input_path = source
                    replacement._input_sha = hashlib.sha256(raw).hexdigest()
                except (OSError, ValueError, TypeError) as exc:
                    wx.MessageBox(str(exc), 'Invalid Study', wx.OK | wx.ICON_ERROR, self)
                    return
                replacement.Show()
                self.Close()

        def _help(self, event):
            from pathlib import Path
            from wayricad_runtime.help import open_help
            filename='PLANE_PORTS.html' if self._result_only else 'AC_PORTS.html'
            open_help(self,Path(__file__).with_name(filename),'Quick PI - AC Two-Port Help')

        def _assert_inputs(self):
            for path,digest in ((self._input_path,self._input_sha),(self._reference_path,self._reference_sha)):
                if path is not None and hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                    raise ValueError('Loaded study or reference changed; reload before running/exporting.')

        def _save(self, event):
            if self.result is None:
                return
            with wx.FileDialog(self, 'Save Two-Port Result', wildcard='JSON files (*.json)|*.json',
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
                if dialog.ShowModal() != wx.ID_OK:
                    return
                try:
                    from pathlib import Path
                    from wayricad_runtime.report_ui import publish_documents
                    target = Path(dialog.GetPath())
                    if target.suffix.lower() != '.json':
                        raise ValueError('Use a separate .json result file.')
                    from wayricad_runtime.report_ui import checked_sources
                    document=dict(self.result)
                    if self.reference is not None:
                        document['comparison_reference']={'label':self.reference_label,'data':self.reference,
                            'source_sha256':self._reference_sha,
                            'basis':'20 log10 of magnitude ratio, common sampled frequencies only'}
                    sources=checked_sources(self.result)+([self._input_path] if self._input_path else [])+(
                        [self._reference_path] if self._reference_path else [])
                    def guard():
                        self._assert_inputs();checked_sources(self.result)
                    publish_documents({target:json.dumps(document,indent=2,allow_nan=False)},
                                      sources=sources,source_guard=guard)
                except (OSError, ValueError) as exc:
                    wx.MessageBox(str(exc), 'Save Failed', wx.OK | wx.ICON_ERROR, self)

        def _close(self, event):
            self.job.close()
            self.Destroy()

    return PortsFrame()


def launch(parent=None, study=None):
    """Launch standalone, or attach to the caller's existing wx application."""
    import wx
    app = wx.GetApp()
    standalone = app is None
    if standalone:
        app = wx.App(False)
    frame = create_frame(parent, study)
    frame.Show()
    if standalone:
        app.MainLoop()
    return frame


if __name__ == '__main__':
    launch()
