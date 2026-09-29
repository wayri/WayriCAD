"""Manual cross-section view for impedance geometries not extracted from PCB."""

import wx

from .cross_section import TOPOLOGIES, estimate


class SectionSketch(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, size=(-1, 180))
        self.topology = "microstrip"
        self.values = (.3, .2, .2)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)

    def set_geometry(self, topology, width, height, gap):
        self.topology, self.values = topology, (width, height, gap)
        self.Refresh()

    def paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(wx.Colour(246, 249, 251)))
        dc.Clear()
        size = self.GetClientSize()
        cx = size.width // 2
        cy = size.height // 2
        w, h, gap = self.values
        scale = min(160, max(45, 90 / max(w, gap, h, .05)))
        trace = max(12, min(180, int(w * scale)))
        slot = max(10, min(100, int(gap * scale)))
        dc.SetPen(wx.Pen(wx.Colour(39, 106, 117), 1))
        dc.SetBrush(wx.Brush(wx.Colour(229, 239, 235)))
        dc.DrawRectangle(20, cy + 8, max(50, size.width - 40), 65)
        dc.SetPen(wx.Pen(wx.Colour(17, 103, 112), 1))
        dc.SetBrush(wx.Brush(wx.Colour(25, 130, 143)))
        pair = self.topology == "edge-coupled-stripline"
        cpw = self.topology in ("cpw", "grounded-cpw")
        if pair:
            dc.DrawRectangle(cx - slot // 2 - trace, cy - 7, trace, 14)
            dc.DrawRectangle(cx + slot // 2, cy - 7, trace, 14)
            dc.DrawText("pair gap", cx - 26, cy - 37)
        else:
            dc.DrawRectangle(cx - trace // 2, cy - 7, trace, 14)
        if cpw:
            dc.SetBrush(wx.Brush(wx.Colour(168, 111, 54)))
            dc.DrawRectangle(20, cy - 7, max(10, cx - trace // 2 - slot - 20), 14)
            dc.DrawRectangle(cx + trace // 2 + slot, cy - 7,
                             max(10, size.width - cx - trace // 2 - slot - 20), 14)
            dc.DrawText("lateral ground", 25, cy - 35)
        if self.topology in ("microstrip", "grounded-cpw", "symmetric-stripline", "edge-coupled-stripline"):
            dc.SetBrush(wx.Brush(wx.Colour(168, 111, 54)))
            dc.DrawRectangle(20, cy + 73, max(50, size.width - 40), 7)
        if self.topology in ("symmetric-stripline", "edge-coupled-stripline"):
            dc.DrawRectangle(20, cy - 60, max(50, size.width - 40), 7)
        dc.SetTextForeground(wx.Colour(35, 54, 68))
        dc.DrawText(f"width {w:g} mm · dielectric/reference {h:g} mm" +
                    (f" · gap {gap:g} mm" if pair or cpw else ""), 24, 8)


class CrossSectionPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)
        root = wx.BoxSizer(wx.VERTICAL)
        explanation = wx.StaticText(self, label="Manual cross-section screening. Enter measured dimensions; these values are not read from the selected route.")
        root.Add(explanation, 0, wx.EXPAND | wx.ALL, 9)
        form = wx.FlexGridSizer(0, 4, 7, 9)
        self.topology = wx.Choice(self, choices=list(TOPOLOGIES))
        self.topology.SetSelection(0)
        self.width = wx.TextCtrl(self, value="0.3")
        self.height = wx.TextCtrl(self, value="0.2")
        self.copper = wx.TextCtrl(self, value="0.035")
        self.gap = wx.TextCtrl(self, value="0.2")
        self.er = wx.TextCtrl(self, value="4.2")
        for label, control in (("Topology", self.topology), ("Trace width (mm)", self.width),
                               ("Reference separation (mm)", self.height), ("Copper thickness (mm)", self.copper),
                               ("Ground slot / pair gap (mm)", self.gap), ("Dielectric Er", self.er)):
            form.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        form.AddGrowableCol(1, 1); form.AddGrowableCol(3, 1)
        root.Add(form, 0, wx.EXPAND | wx.ALL, 9)
        self.sketch = SectionSketch(self)
        root.Add(self.sketch, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 9)
        self.answer = wx.StaticText(self, label="")
        root.Add(self.answer, 0, wx.EXPAND | wx.ALL, 9)
        self.limits = wx.StaticText(self, label="Quasi-static homogeneous cross section. No soldermask, vias, finite ground, losses or protocol compliance.")
        root.Add(self.limits, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 9)
        self.SetSizer(root)
        self.topology.Bind(wx.EVT_CHOICE, self._mode)
        for control in (self.width, self.height, self.copper, self.gap, self.er):
            control.Bind(wx.EVT_TEXT, self._update)
        self._update(None)

    def _mode(self, event):
        if self.topology.GetStringSelection() in ("cpw", "grounded-cpw", "edge-coupled-stripline"):
            self.copper.SetValue("0")
        self._update(event)

    def _update(self, _event):
        topology = self.topology.GetStringSelection()
        try:
            w, h, t, gap, er = [float(control.GetValue()) for control in
                                 (self.width, self.height, self.copper, self.gap, self.er)]
            self.sketch.set_geometry(topology, w, h, gap)
            result = estimate(topology, w, h, er, copper_mm=t, gap_mm=gap)
            quantity = "differential_z0_ohm" if topology == "edge-coupled-stripline" else "single_ended_z0_ohm"
            self.answer.SetLabel(f"{quantity.replace('_', ' ')}: {result[quantity]:.3f} Ω   ·   effective Er: {result['effective_permittivity']:.4g}")
        except (ValueError, OverflowError) as exc:
            self.answer.SetLabel("Unresolved: " + str(exc))
        self.Layout()
