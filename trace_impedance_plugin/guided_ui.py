"""Consistent guided workflow widgets for standalone KiWay plugins."""

from __future__ import annotations

from typing import Sequence

import wx


ACCENT = "#3399cc"
DONE_BG, DONE_FG = "#dcefe3", "#174c2c"
ACTIVE_BG, ACTIVE_FG = "#d9eaff", "#123f67"
PENDING_BG, PENDING_FG = "#e8eaed", "#3c4043"


class WorkflowGuide:
    """Compact, theme-safe step indicator with progress and next action."""

    def __init__(self, parent: wx.Window, title: str, summary: str, steps: Sequence[str]) -> None:
        self.panel = wx.Panel(parent)
        self.steps = list(steps)
        root = wx.BoxSizer(wx.HORIZONTAL)
        accent = wx.Panel(self.panel, size=(5, -1))
        accent.SetBackgroundColour(wx.Colour(ACCENT))
        root.Add(accent, 0, wx.EXPAND)

        content = wx.BoxSizer(wx.VERTICAL)
        heading_row = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self.panel, label=title)
        heading.SetFont(heading.GetFont().Bold().Larger())
        heading_row.Add(heading, 0, wx.ALIGN_CENTER_VERTICAL)
        heading_row.AddStretchSpacer()
        self.progress = wx.StaticText(self.panel, label="")
        progress_font = self.progress.GetFont()
        progress_font.MakeSmaller()
        self.progress.SetFont(progress_font)
        self.progress.SetForegroundColour(wx.Colour("#6b7a89"))
        heading_row.Add(self.progress, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 12)
        content.Add(heading_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.subtitle = wx.StaticText(self.panel, label=summary)
        self.subtitle.Wrap(760)
        content.Add(self.subtitle, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 8)

        row = wx.WrapSizer(wx.HORIZONTAL)
        self.labels = []
        for index, step in enumerate(self.steps, 1):
            label = wx.StaticText(self.panel, label=f" {index}  {step} ", style=wx.ALIGN_CENTER | wx.BORDER_SIMPLE)
            label.SetMinSize((108, 30))
            row.Add(label, 0, wx.RIGHT, 6)
            self.labels.append(label)
        content.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        self.next_action = wx.StaticText(self.panel, label="")
        self.next_action.Wrap(760)
        content.Add(self.next_action, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        content.Add(wx.StaticLine(self.panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        root.Add(content, 1, wx.EXPAND)
        self.panel.SetSizer(root)
        self.panel.Bind(wx.EVT_SIZE, self._on_size)
        self.active_step = 0
        self.set_step(0, "Review the settings, then use the primary action below.")

    def _on_size(self, event: wx.SizeEvent) -> None:
        width = max(420, event.GetSize().width - 48)
        self.subtitle.Wrap(width)
        self.next_action.Wrap(width)
        self.panel.Layout()
        event.Skip()

    def set_step(self, active: int, next_action: str) -> None:
        self.active_step = active
        for index, label in enumerate(self.labels):
            if index < active:
                background, foreground, text = DONE_BG, DONE_FG, f" \u2713  {self.steps[index]} "
            elif index == active:
                background, foreground, text = ACTIVE_BG, ACTIVE_FG, f" {index + 1}  {self.steps[index]} "
            else:
                background, foreground, text = PENDING_BG, PENDING_FG, f" {index + 1}  {self.steps[index]} "
            label.SetLabel(text)
            label.SetBackgroundColour(wx.Colour(background))
            label.SetForegroundColour(wx.Colour(foreground))
            if index == active:
                font = label.GetFont()
                if not font.Bold():
                    label.SetFont(font.Bold())
            else:
                font = label.GetFont()
                if font.Bold():
                    font.MakeBold(False)
                    label.SetFont(font)
        total = len(self.steps)
        current = min(max(active, 0), total)
        self.progress.SetLabel(f"step {min(current + 1, total)} of {total}" if active < total else "complete")
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
