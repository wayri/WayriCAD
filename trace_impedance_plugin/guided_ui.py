"""Consistent guided workflow widgets for standalone KiWay plugins."""

from __future__ import annotations

from typing import Sequence

import wx


class WorkflowGuide:
    """Compact, theme-safe step indicator with one explicit next action."""

    def __init__(self, parent: wx.Window, title: str, summary: str, steps: Sequence[str]) -> None:
        self.panel = wx.Panel(parent)
        root = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self.panel, label=title)
        heading.SetFont(heading.GetFont().Bold().Larger())
        root.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.subtitle = wx.StaticText(self.panel, label=summary)
        self.subtitle.Wrap(760)
        root.Add(self.subtitle, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        row = wx.WrapSizer(wx.HORIZONTAL)
        self.labels = []
        for index, step in enumerate(steps, 1):
            label = wx.StaticText(self.panel, label=f" {index}  {step} ", style=wx.ALIGN_CENTER | wx.BORDER_SIMPLE)
            label.SetMinSize((108, 30))
            row.Add(label, 0, wx.RIGHT, 6)
            self.labels.append(label)
        root.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        self.next_action = wx.StaticText(self.panel, label="")
        self.next_action.Wrap(760)
        root.Add(self.next_action, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(wx.StaticLine(self.panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.panel.SetSizer(root)
        self.panel.Bind(wx.EVT_SIZE, self._on_size)
        self.set_step(0, "Review the settings, then use the primary action below.")

    def _on_size(self, event: wx.SizeEvent) -> None:
        width = max(420, event.GetSize().width - 32)
        self.subtitle.Wrap(width)
        self.next_action.Wrap(width)
        self.panel.Layout()
        event.Skip()

    def set_step(self, active: int, next_action: str) -> None:
        for index, label in enumerate(self.labels):
            if index < active:
                background, foreground = "#dcefe3", "#174c2c"
            elif index == active:
                background, foreground = "#d9eaff", "#123f67"
            else:
                background, foreground = "#e8eaed", "#3c4043"
            label.SetBackgroundColour(wx.Colour(background))
            label.SetForegroundColour(wx.Colour(foreground))
        self.next_action.SetLabel(f"Next: {next_action}")
        self.panel.Layout()


def add_workflow(
    parent: wx.Window,
    sizer: wx.Sizer,
    title: str,
    summary: str,
    steps: Sequence[str],
) -> WorkflowGuide:
    guide = WorkflowGuide(parent, title, summary, steps)
    sizer.Add(guide.panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 6)
    return guide
