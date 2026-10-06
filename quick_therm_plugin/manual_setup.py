"""Explicit per-component inputs for boards without saved thermal fields."""

from __future__ import annotations

import wx
import wx.grid

from .quick_therm import parse_field_quantity


class ManualThermalDialog(wx.Dialog):
    def __init__(self, parent, references, environment, heatsinks, existing,
                 power_only=False):
        super().__init__(parent, title="QuickTherm · Enter component inputs",
                         size=(680, min(780, max(360, 190 + 31 * len(references)))),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.references = list(references)
        self.environment = environment
        self.heatsinks = set(heatsinks)
        self.power_only = power_only
        self.values = None
        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(panel, label=(
            "Enter dissipated power for every selected part. RθJB is optional and is used only "
            "to estimate a package junction from the solved board site. No resistance is inferred."
            if power_only else
            "Enter dissipated power and the applicable thermal resistance for every selected part. "
            "Use values for this board and cooling environment; no values are inferred from geometry. "
            "Entries stay in this window and do not change the PCB."
        ))
        note.Wrap(620)
        layout.Add(note, 0, wx.EXPAND | wx.ALL, 12)
        self.grid = wx.grid.Grid(panel)
        self.grid.CreateGrid(len(self.references), 3)
        self.grid.SetRowLabelSize(100)
        self.grid.SetColLabelValue(0, "Power (W)")
        self.grid.SetColLabelValue(1, "Optional RθJB (K/W)" if power_only else "Rθ (K/W)")
        self.grid.SetColLabelValue(2, "Resistance path")
        self.grid.SetColSize(0, 130)
        self.grid.SetColSize(1, 130)
        self.grid.SetColSize(2, 220)
        for index, ref in enumerate(self.references):
            quantity = self._resistance_quantity(ref)
            self.grid.SetRowLabelValue(index, ref)
            self.grid.SetCellValue(index, 2, "Junction → board (optional)" if power_only else
                                   "Junction → case" if ref in self.heatsinks else
                                   "Junction → ambient" if environment == "air" else "Junction → board")
            self.grid.SetReadOnly(index, 2)
            previous = existing.get(ref, {})
            for column, key in ((0, "power_w"), (1, "theta_jb_k_per_w" if power_only else quantity)):
                if key in previous:
                    self.grid.SetCellValue(index, column, str(previous[key]))
        layout.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.error = wx.StaticText(panel, label=("Power may be zero; optional RθJB must be positive."
                                                if power_only else
                                                "Power may be zero; thermal resistance must be positive."))
        layout.Add(self.error, 0, wx.EXPAND | wx.ALL, 12)
        buttons = wx.StdDialogButtonSizer()
        accept = wx.Button(panel, wx.ID_OK, "Use these values")
        buttons.AddButton(accept)
        buttons.AddButton(wx.Button(panel, wx.ID_CANCEL))
        buttons.Realize()
        layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        accept.Bind(wx.EVT_BUTTON, self._accept)
        self.CentreOnParent()

    def _resistance_quantity(self, ref):
        if ref in self.heatsinks:
            return "theta_jc_k_per_w"
        return "theta_ja_air_k_per_w" if self.environment == "air" else "theta_jb_k_per_w"

    def _accept(self, event):
        self.grid.DisableCellEditControl()
        entered = {}
        try:
            for index, ref in enumerate(self.references):
                resistance = "theta_jb_k_per_w" if self.power_only else self._resistance_quantity(ref)
                values = {}
                for column, key in ((0, "power_w"), (1, resistance)):
                    raw = self.grid.GetCellValue(index, column).strip()
                    if not raw:
                        if self.power_only and column == 1:
                            continue
                        raise ValueError(f"{ref}: enter {key}; no default is assumed.")
                    try:
                        values[key] = parse_field_quantity(raw, key)
                    except ValueError as exc:
                        raise ValueError(f"{ref}: {exc}") from exc
                entered[ref] = values
        except ValueError as exc:
            self.error.SetLabel(str(exc))
            self.error.SetForegroundColour(wx.Colour(175, 35, 35))
            self.Layout()
            return
        self.values = entered
        self.EndModal(wx.ID_OK)
