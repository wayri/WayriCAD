"""Reviewed sheet-occurrence and routed PCB section import."""
from pathlib import Path
import json
import wx
from .management_gui import RepairDialog
from .sections import list_sections, suggest_region, preview_section, apply_section


class SectionDialog(RepairDialog):
    def __init__(self, parent, spec, cli_path=''):
        wx.Dialog.__init__(self, parent, title='Add subsheet and routed layout — '+spec.alias,
                           size=(960, 780), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.spec, self.cli_path = spec, cli_path
        self.plan = self.result = None
        self.busy = False
        self.instances = []
        panel = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(self, label='Select one exact sheet occurrence, including its descendants, and a PCB rectangle in millimetres. Complete contained routing, vias, zones and drawings are preserved. Crossing copper, unrelated footprints and ambiguous groups stop extraction. Preview verifies electrical partitions and native schematic/PCB parity before creating a new source copy.')
        note.Wrap(900)
        panel.Add(note, 0, wx.ALL | wx.EXPAND, 12)
        self.sheet = wx.Choice(self)
        panel.Add(self.sheet, 0, wx.ALL | wx.EXPAND, 12)
        coordinates = wx.BoxSizer(wx.HORIZONTAL)
        self.coords = []
        for label in ('X1', 'Y1', 'X2', 'Y2'):
            coordinates.Add(wx.StaticText(self, label=label+' (mm)'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            control = wx.TextCtrl(self, value='0', size=(100,-1))
            control.Bind(wx.EVT_TEXT, lambda event: self.invalidate())
            self.coords.append(control)
            coordinates.Add(control, 0, wx.RIGHT, 12)
        panel.Add(coordinates, 0, wx.ALL, 12)
        self.blank = wx.Button(self, label='Suggest rectangle around selected footprints')
        self.blank.Bind(wx.EVT_BUTTON, self.on_suggest)
        panel.Add(self.blank, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.report = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        panel.Add(self.report, 1, wx.ALL | wx.EXPAND, 12)
        self.status = wx.StaticText(self, label='Reading saved sheet instances…')
        panel.Add(self.status, 0, wx.ALL | wx.EXPAND, 12)
        self.preview = wx.Button(self, label='Preview section')
        self.create = wx.Button(self, label='Create section copy and add to merge…')
        self.cancel = wx.Button(self, wx.ID_CANCEL, 'Close')
        self.preview.Bind(wx.EVT_BUTTON, self.on_preview)
        self.create.Bind(wx.EVT_BUTTON, self.on_create)
        self.sheet.Bind(wx.EVT_CHOICE, lambda event: self.invalidate())
        self.Bind(wx.EVT_CLOSE, self.on_close)
        row = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self.preview, self.create, self.cancel): row.Add(button, 0, wx.RIGHT, 8)
        panel.Add(row, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizer(panel)
        self.create.Disable()
        self.CentreOnParent()
        wx.CallAfter(self.load_instances)

    def run(self, action, done):
        if self.busy: return
        self.sheet.Disable()
        for control in self.coords: control.Disable()
        super().run(action, done)
        self.status.SetLabel('Reading and validating the saved section…')

    def finish(self, done, result, error):
        self.sheet.Enable()
        for control in self.coords: control.Enable()
        super().finish(done, result, error)

    def load_instances(self):
        def done(instances):
            self.instances = instances
            self.sheet.SetItems([f"{item['display_path']} — {item['descendant_symbols']} symbols — {item['sheet_path']}" for item in instances])
            if instances: self.sheet.SetSelection(0)
            self.status.SetLabel('Choose a sheet instance and review its PCB rectangle.')
        self.run(lambda: list_sections(self.spec), done)

    def selection(self):
        index = self.sheet.GetSelection()
        if not 0 <= index < len(self.instances): raise ValueError('Choose one sheet occurrence.')
        return self.instances[index]['sheet_path']

    def on_suggest(self, event):
        try: path = self.selection()
        except Exception as exc:
            self.report.SetValue(str(exc)); return
        def done(region):
            for control, value in zip(self.coords, region): control.SetValue(str(value))
            self.status.SetLabel('Suggested footprint rectangle. Enlarge as needed for routing, then preview.')
        self.run(lambda: suggest_region(self.spec, path, self.cli_path), done)

    def on_preview(self, event):
        try:
            path = self.selection()
            region = [float(control.GetValue()) for control in self.coords]
        except Exception as exc:
            self.invalidate(); self.report.SetValue(str(exc)); return
        def done(plan):
            self.plan = plan
            self.report.SetValue(json.dumps(plan['report'], indent=2, ensure_ascii=False))
            self.create.Enable()
            self.status.SetLabel('Preview ready. Review counts, boundary connections and DRC findings before adding this source.')
        self.run(lambda: preview_section(self.spec, path, region, self.cli_path), done)

    def on_create(self, event):
        if self.plan is None: return
        with wx.DirDialog(self, 'Choose a parent folder for a NEW extracted source') as dialog:
            if dialog.ShowModal() != wx.ID_OK: return
            occurrence = self.plan['sheet_path'].rsplit('/',1)[-1][:8]
            destination = Path(dialog.GetPath()) / (Path(self.spec.project).stem+'-FusionSection-'+occurrence)
        plan = self.plan
        def done(spec):
            self.result = spec
            self.EndModal(wx.ID_OK)
        self.run(lambda: apply_section(plan, destination), done)
