"""Native explicit coupon/material forms for the magnetics thermal screen."""
import copy
import json
import threading

import wx
from matplotlib.figure import Figure

from .plot_canvas import FigureCanvasWxAgg
from .thermal_coupling import (
    ThermalDrive, rectangular_profile, require_fresh, solve_thermal_study,
)


def _solve_worker(snapshot, cancelled, closed, dispatch_lock, complete):
    """Only plain data crosses this boundary; never read native controls here."""
    study, error = None, None
    try:
        study = solve_thermal_study(*snapshot, cancel=cancelled.is_set)
    except InterruptedError:
        cancelled.set()
    except Exception as exc:
        error = str(exc)
    # Serialize scheduling with teardown. A previously queued callback also
    # checks closed before it touches any native window.
    with dispatch_lock:
        if not closed.is_set():
            wx.CallAfter(complete, study, error)


class ThermalDialog(wx.Dialog):
    def __init__(self, parent, result):
        super().__init__(parent, title="Primary winding thermal study", size=(1060, 780),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetMinSize((800, 620))
        self.result = result
        self.study = None
        self._closed = threading.Event()
        self._dispatch_lock = threading.Lock()
        self._cancelled = None
        self._worker = None
        self._generation = 0
        self.fields = {}
        root = wx.BoxSizer(wx.VERTICAL)
        tabs = wx.Notebook(self)
        tabs.SetMinSize((-1, 285))
        groups = [
            ("Board / material", [
                ("width", "Coupon width (mm)", result.spec.outer_width_mm+10),
                ("height", "Coupon height (mm)", result.spec.outer_height_mm+10),
                ("layers", "Physical copper layers", max(2, result.spec.layers)),
                ("spacing", "Copper midplane spacing (mm)", 1.6/max(1,result.spec.layers-1)),
                ("dielectric", "Dielectric conductivity (W/m/K)", .3),
                ("copper", "Copper conductivity (W/m/K)", 385),
                ("grid", "Long-axis grid cells", 24)]),
            ("Boundary / drive", [
                ("ambient", "Ambient (C)", 20),
                ("h", "Face convection (W/m2/K)", 10),
                ("emissivity", "Board emissivity (0-1)", .85),
                ("value", "Drive value (A or V)", result.spec.current_a),
                ("reference", "Copper reference temperature (C)", 20),
                ("alpha", "Copper coefficient (1/K)", .00393),
                ("ceiling", "Validity ceiling (C)", 200)]),
            ("Core contact", [
                ("core_power", "Board-entering core heat (W)", 0),
                ("core_x", "Contact centre X (mm)", 0),
                ("core_y", "Contact centre Y (mm)", 0),
                ("core_w", "Contact width (mm)", 5),
                ("core_h", "Contact height (mm)", 5),
                ("core_layer", "Physical contact layer index", 0)])]
        for title, entries in groups:
            panel = wx.ScrolledWindow(tabs)
            panel.SetScrollRate(8, 12)
            form = wx.FlexGridSizer(0, 2, 7, 12)
            form.AddGrowableCol(1)
            for key, label, value in entries:
                form.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                self.fields[key] = wx.TextCtrl(panel, value=str(value))
                form.Add(self.fields[key], 1, wx.EXPAND)
                self.fields[key].Bind(wx.EVT_TEXT, self.invalidate)
            if title == "Boundary / drive":
                form.Add(wx.StaticText(panel, label="Drive mode"))
                self.mode = wx.Choice(panel, choices=["current", "voltage"])
                self.mode.SetSelection(0)
                form.Add(self.mode, 1, wx.EXPAND)
                self.mode.Bind(wx.EVT_CHOICE, self.invalidate)
                form.Add(wx.StaticText(panel, label="Resistance model"))
                self.loss = wx.Choice(panel, choices=["dc", "legacy_ac"])
                self.loss.SetSelection(0)
                form.Add(self.loss, 1, wx.EXPAND)
                self.loss.Bind(wx.EVT_CHOICE, self.invalidate)
            if title == "Core contact":
                self.core_enabled = wx.CheckBox(panel, label="Include prescribed core contact heat")
                form.Add(self.core_enabled)
                form.AddSpacer(1)
                self.core_enabled.Bind(wx.EVT_CHECKBOX, self.invalidate)
            wrapper = wx.BoxSizer(wx.VERTICAL)
            wrapper.Add(form, 1, wx.EXPAND | wx.ALL, 12)
            panel.SetSizer(wrapper)
            tabs.AddPage(panel, title)
        root.Add(tabs, 0, wx.EXPAND | wx.ALL, 8)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.run_button = wx.Button(self, label="Solve thermal study")
        self.run_button.Bind(wx.EVT_BUTTON, self.solve)
        actions.Add(self.run_button, 0, wx.RIGHT, 8)
        self.cancel_button = wx.Button(self, label="Cancel")
        self.cancel_button.Enable(False)
        self.cancel_button.SetToolTip("Cancel between solver steps; an active linear solve cannot be interrupted.")
        self.cancel_button.Bind(wx.EVT_BUTTON, self.cancel)
        actions.Add(self.cancel_button, 0, wx.RIGHT, 8)
        self.export_button = wx.Button(self, label="Export reviewed JSON")
        self.export_button.Enable(False)
        self.export_button.Bind(wx.EVT_BUTTON, self.export)
        actions.Add(self.export_button, 0, wx.RIGHT, 12)
        self.layer = wx.Choice(self)
        self.layer.Enable(False)
        self.layer.Bind(wx.EVT_CHOICE, self.plot)
        actions.Add(self.layer, 1)
        root.Add(actions, 0, wx.EXPAND | wx.ALL, 8)
        self.summary = wx.TextCtrl(self, style=wx.TE_READONLY | wx.TE_MULTILINE,
                                   size=(-1, 100))
        root.Add(self.summary, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.figure = Figure(figsize=(6, 3), constrained_layout=True)
        self.canvas = FigureCanvasWxAgg(self, -1, self.figure)
        root.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(root)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _deactivate(self):
        with self._dispatch_lock:
            self._closed.set()
            if self._cancelled is not None:
                self._cancelled.set()

    def _on_close(self, event):
        self._deactivate()
        event.Skip()

    def _on_destroy(self, event):
        if event.GetEventObject() is self:
            self._deactivate()
        event.Skip()

    def Destroy(self):
        self._deactivate()
        return super().Destroy()

    def invalidate(self, event):
        self._generation += 1
        if self._cancelled is not None:
            self._cancelled.set()
        self.study = None
        if hasattr(self, "export_button"):
            self.export_button.Enable(False)
            self.layer.Enable(False)
            self.summary.SetValue("")
            self.figure.clear()
            self.canvas.draw_idle()
            if self._worker is not None:
                self.cancel_button.Enable(False)
                self.summary.SetValue("Inputs changed; cancelling. An active linear solve cannot be interrupted.")
        event.Skip()

    def inputs(self):
        f = lambda key: float(self.fields[key].GetValue())
        integer = lambda key: int(self.fields[key].GetValue())
        geometry = rectangular_profile(f("width"), f("height"), integer("layers"),
                                       f("spacing"), self.result.spec.copper_um)
        settings = dict(ambient_c=f("ambient"), dielectric_k_w_mk=f("dielectric"),
                        copper_k_w_mk=f("copper"), via_plating_mm=.025,
                        board_h_w_m2k=f("h"), board_emissivity=f("emissivity"),
                        grid_cells_long_axis=integer("grid"), copper_blur_cells=1)
        drive = ThermalDrive(mode=self.mode.GetStringSelection(), value=f("value"),
                             reference_c=f("reference"), copper_alpha_per_k=f("alpha"),
                             resistance_model=self.loss.GetStringSelection(), maximum_c=f("ceiling"))
        contact = None
        if self.core_enabled.GetValue():
            x, y, w, h = [f(key) for key in ("core_x", "core_y", "core_w", "core_h")]
            if w <= 0 or h <= 0:
                raise ValueError("Core contact dimensions must be positive.")
            contact = dict(power_w=f("core_power"), layer_id=integer("core_layer"),
                           polygon_mm=[[x-w/2,y-h/2],[x+w/2,y-h/2],
                                       [x+w/2,y+h/2],[x-w/2,y+h/2]])
        return (self.result, geometry, settings, drive, list(range(self.result.spec.layers)),
                (-self.result.spec.outer_width_mm/2, -self.result.spec.outer_height_mm/2), contact)

    def solve(self, event):
        if self._closed.is_set() or self._worker is not None:
            return
        self.study = None
        self.export_button.Enable(False)
        self.layer.Enable(False)
        self.summary.SetValue("")
        self.figure.clear()
        self.canvas.draw_idle()
        try:
            snapshot = copy.deepcopy(self.inputs())
        except Exception as exc:
            wx.MessageBox(str(exc), "Thermal study failed", wx.OK | wx.ICON_ERROR, self)
            return
        generation = self._generation
        cancelled = threading.Event()
        self._cancelled = cancelled
        self.run_button.Enable(False)
        self.cancel_button.Enable(True)
        self.summary.SetValue("Solving thermal study...")
        complete = lambda study, error: self._complete(generation, cancelled, study, error)
        self._worker = threading.Thread(target=_solve_worker,
            args=(snapshot, cancelled, self._closed, self._dispatch_lock, complete),
            name="magnetics-thermal", daemon=True)
        try:
            self._worker.start()
        except Exception as exc:
            self._complete(generation, cancelled, None, str(exc))

    def cancel(self, event):
        if self._closed.is_set() or self._cancelled is None:
            return
        self._cancelled.set()
        self.cancel_button.Enable(False)
        self.summary.SetValue("Cancelling; an active linear solve cannot be interrupted.")

    def _complete(self, generation, cancelled, study, error):
        if self._closed.is_set():
            return
        self._worker = None
        self._cancelled = None
        self.run_button.Enable(True)
        self.cancel_button.Enable(False)
        if cancelled.is_set() or generation != self._generation:
            self.summary.SetValue("Thermal study cancelled; no results accepted.")
            return
        try:
            if error is not None:
                raise ValueError(error)
            require_fresh(study, *self.inputs())
            self.study = study
            s = self.study
            balance = s["thermal"]["heat_balance"]
            core_heat = ("excluded" if s['core_contact_power_w'] is None else
                         f"{s['core_contact_power_w']:.6g} W")
            self.summary.SetValue(
                f"Primary trace: {s['trace_loss_w']:.6g} W; {s['current_a']:.6g} A; "
                f"{s['resistance_ohm']:.6g} ohm\n"
                f"Winding mean / supported cell peak: {s['winding_mean_c']:.3f} / {s['winding_peak_c']:.3f} C; "
                f"heat residual: {balance['residual_w']:.3g} W\n"
                f"Core contact heat: {core_heat}; via/secondary heat excluded")
            self.layer.SetItems([row["name"] for row in s["thermal"]["layers"]])
            self.layer.SetSelection(0)
            self.layer.Enable(True)
            self.plot(None)
            self.export_button.Enable(True)
        except Exception as exc:
            self.study = None
            self.export_button.Enable(False)
            self.layer.Enable(False)
            self.figure.clear()
            self.canvas.draw_idle()
            self.summary.SetValue("")
            wx.MessageBox(str(exc), "Thermal study failed", wx.OK | wx.ICON_ERROR, self)

    def plot(self, event):
        if not self.study:
            return
        import numpy as np
        row = self.study["thermal"]["layers"][self.layer.GetSelection()]
        self.figure.clear()
        axes = self.figure.add_subplot(111)
        mesh = axes.pcolormesh(row["x_edges_mm"], row["y_edges_mm"],
                               np.asarray(row["values_c"], dtype=float), cmap="inferno")
        self.figure.colorbar(mesh, ax=axes, label="Temperature (C)")
        axes.set(xlabel="X (mm)", ylabel="Y (mm)", title=row["name"], aspect="equal")
        self.canvas.draw_idle()

    def export(self, event):
        try:
            require_fresh(self.study, *self.inputs())
            with wx.FileDialog(self, "Export thermal study", wildcard="JSON (*.json)|*.json",
                               style=wx.FD_SAVE) as dialog:
                if dialog.ShowModal() == wx.ID_OK:
                    with open(dialog.GetPath(), "x", encoding="utf-8") as stream:
                        json.dump(self.study, stream, indent=2, allow_nan=False)
        except Exception as exc:
            wx.MessageBox(str(exc), "Thermal export failed", wx.OK | wx.ICON_ERROR, self)
