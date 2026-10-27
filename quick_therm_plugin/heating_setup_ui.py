"""Small native guide over QuickTherm's existing spatial heat solver inputs."""
import wx
from .heating_setup import heating_settings, heating_advice


class HeatingStudyDialog(wx.Dialog):
    """Review source coverage, cooling assumptions and bounded playback inputs."""
    def __init__(self, parent, settings, sources, environment, transient=False, schedules=None):
        super().__init__(parent, title="QuickTherm · Heating study", size=(760, 720),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize(self.FromDIP((560, 480)))
        self.settings = None
        self.run_after_apply = False
        self.schedules = schedules or {}
        layout = wx.BoxSizer(wx.VERTICAL)
        scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 12)
        self.scroll=scroll
        self._wrapped=[]
        content = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(scroll, label="1  Review included heat sources")
        content.Add(note, 0, wx.ALL, 10)
        table = wx.ListCtrl(scroll, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        table.InsertColumn(0, "Component", width=180)
        table.InsertColumn(1, "Base dissipation · W", width=190)
        known = 0.; missing = []
        for reference, watts in sources:
            index = table.InsertItem(table.GetItemCount(), reference)
            table.SetItem(index, 1, "Unknown" if watts is None else f"{watts:.6g}")
            if watts is None: missing.append(reference)
            else: known += watts
        table.SetMinSize((-1, self.FromDIP(110)))
        content.Add(table, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        coverage = f"{len(sources)} included sources · known total {known:.6g} W"
        if missing: coverage += f" · {len(missing)} unknown; enter these in Component inputs before running."
        summary = wx.StaticText(scroll, label=coverage)
        self._wrapped.append((summary,coverage)); content.Add(summary, 0, wx.EXPAND | wx.ALL, 10)
        boundary = wx.StaticText(scroll, label="2  Cooling boundary\n" + environment +
            "\nMaterial and boundary values remain in the main setup. This guide does not infer cooling from geometry.")
        self._wrapped.append((boundary,boundary.GetLabel())); content.Add(boundary, 0, wx.EXPAND | wx.ALL, 10)
        content.Add(wx.StaticText(scroll, label="3  Choose steady state or time-varying heating"), 0, wx.ALL, 10)
        self.mode = wx.Choice(scroll, choices=["Steady state", "Time-varying board heating"])
        self.mode.SetSelection(int(transient)); content.Add(self.mode, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        form = wx.FlexGridSizer(0, 2, 7, 10); form.AddGrowableCol(1)
        self.fields = {}
        for key, label in (("duration_s", "Duration · s / ms / min / h"),
                           ("timestep_s", "Maximum solver step · s / ms"),
                           ("frame_interval_s", "Stored frame interval · s / ms"),
                           ("initial_c", "Initial temperature · °C"),
                           ("copper_volumetric_capacity_j_m3k", "Copper capacity · J/(m³·K)"),
                           ("dielectric_volumetric_capacity_j_m3k", "Dielectric capacity · J/(m³·K)")):
            form.Add(wx.StaticText(scroll, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            field = wx.TextCtrl(scroll, value=str(settings[key])); self.fields[key] = field
            form.Add(field, 1, wx.EXPAND); field.Bind(wx.EVT_TEXT, self._refresh)
        content.Add(form, 0, wx.EXPAND | wx.ALL, 10)
        self.smooth = wx.Button(scroll, label="Use 100 playback intervals")
        self.smooth.SetToolTip("Explicitly choose duration / 100 for real stored solutions, and reduce the maximum solver step if needed. This does not establish time convergence.")
        self.smooth.Bind(wx.EVT_BUTTON, self._smooth)
        content.Add(self.smooth, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.advice = wx.StaticText(scroll, label="")
        content.Add(self.advice, 0, wx.EXPAND | wx.ALL, 10)
        caution = wx.StaticText(scroll, label="Heat capacities must be reviewed; existing defaults are illustrative. Time-varying heating selects the multilayer board model. Stored frames are computed states, not interpolated temperatures. Imported PI losses stay fixed unless scheduled explicitly.")
        self._wrapped.append((caution,caution.GetLabel())); content.Add(caution, 0, wx.EXPAND | wx.ALL, 10)
        scroll.SetSizer(content); layout.Add(scroll, 1, wx.EXPAND)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        cancel = wx.Button(self, wx.ID_CANCEL)
        self.apply = wx.Button(self, label="Apply setup")
        self.run = wx.Button(self, label="Apply and run")
        for button in (cancel, self.apply, self.run):
            button.SetMinSize(self.FromDIP((120, -1))); buttons.Add(button, 0, wx.ALL, 6)
        self.apply.Bind(wx.EVT_BUTTON, lambda event: self._apply(False))
        self.run.Bind(wx.EVT_BUTTON, lambda event: self._apply(True))
        layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
        self.SetSizer(layout); scroll.Bind(wx.EVT_SIZE,self._wrap_labels); self.mode.Bind(wx.EVT_CHOICE, self._refresh)
        self._refresh()

    def _values(self):
        return heating_settings({key: field.GetValue() for key, field in self.fields.items()})

    def _refresh(self, event=None):
        transient = self.mode.GetSelection() == 1
        for field in self.fields.values(): field.Enable(transient)
        self.smooth.Enable(transient)
        valid = True
        if transient:
            try:
                advice = heating_advice(self._values(), self.schedules)
                text = (f"{advice['regular_frames']} regular stored frames; at most {advice['frame_upper_bound']} with schedule events.\n"
                        f"At most {advice['step_upper_bound']} integration intervals before duplicate times merge.\n"
                        f"Five-million-value storage budget: at most {advice['nodes_per_frame_budget']:,} nodes per frame at that bound.\n" + advice['note'])
                if advice['frame_upper_bound'] > 1000 or advice['step_upper_bound'] > 10000:
                    text += "\nEvent-aware limits may be exceeded; shorten the study or increase intervals. The solver validates exact times."
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                text = str(error); valid = False
        else:
            text = "Steady state retains the current model and cooling settings. Time fields are retained for later use."
        self._advice_text=text
        self.apply.Enable(valid); self.run.Enable(valid); self._wrap_labels()

    def _wrap_labels(self,event=None):
        if getattr(self,'_wrapping',False):
            if event:event.Skip()
            return
        self._wrapping=True
        try:
            width=max(200,self.scroll.GetClientSize().width-self.FromDIP(32))
            for control,text in self._wrapped+[(self.advice,getattr(self,'_advice_text',''))]:
                control.SetMinSize((1,-1));control.SetLabel(text);control.Wrap(width)
            self.scroll.Layout();self.scroll.FitInside()
        finally:self._wrapping=False
        if event:event.Skip()

    def _smooth(self, event=None):
        from .heating_setup import time_seconds
        try:
            interval = time_seconds(self.fields['duration_s'].GetValue(), 'Duration') / 100
            self.fields['frame_interval_s'].ChangeValue(f"{interval:.9g}")
            step = time_seconds(self.fields['timestep_s'].GetValue(), 'Maximum solver step')
            self.fields['timestep_s'].ChangeValue(f"{min(step, interval):.9g}")
        except ValueError as error:
            self.advice.SetLabel(str(error)); return
        self._refresh()

    def _apply(self, run):
        try:
            self.settings = self._values() if self.mode.GetSelection() == 1 else None
        except ValueError as error:
            self.advice.SetLabel(str(error)); return
        self.run_after_apply = run
        self.EndModal(wx.ID_OK)
