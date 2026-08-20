"""KiCad-native guided workflow components for KiWay workbenches."""

from __future__ import annotations

from typing import Callable, Sequence

import wx


MARGIN = 10
CONTROL_GAP = 7


class WorkflowGuide:
    """Theme-aware title, workflow steps, and contextual next action."""

    def __init__(
        self,
        parent: wx.Window,
        title: str,
        summary: str,
        steps: Sequence[str],
        help_handler: Callable[[wx.CommandEvent], None] | None = None,
    ) -> None:
        self.panel = wx.Panel(parent)
        root = wx.BoxSizer(wx.VERTICAL)

        header = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self.panel, label=title)
        heading.SetFont(heading.GetFont().Bold().Larger())
        header.Add(heading, 1, wx.ALIGN_CENTER_VERTICAL)
        if help_handler is not None:
            bitmap = wx.ArtProvider.GetBitmap(wx.ART_HELP, wx.ART_BUTTON, (20, 20))
            help_button = wx.BitmapButton(self.panel, bitmap=bitmap)
            help_button.SetToolTip("Open the integrated help and troubleshooting guide")
            help_button.Bind(wx.EVT_BUTTON, help_handler)
            header.Add(help_button, 0, wx.LEFT, MARGIN)
        root.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, MARGIN)

        subtitle = wx.StaticText(self.panel, label=summary)
        self.subtitle = subtitle
        root.Add(subtitle, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, MARGIN)

        step_row = wx.BoxSizer(wx.HORIZONTAL)
        self.labels: list[wx.StaticText] = []
        for index, step in enumerate(steps, 1):
            label = wx.StaticText(
                self.panel,
                label=f" {index}  {step} ",
                style=wx.ALIGN_CENTER | wx.BORDER_SIMPLE,
            )
            label.SetMinSize((116, 30))
            step_row.Add(label, 1, wx.EXPAND | wx.RIGHT, 6)
            self.labels.append(label)
        root.Add(step_row, 0, wx.EXPAND | wx.ALL, MARGIN)

        self.next_action = wx.StaticText(self.panel)
        root.Add(self.next_action, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, MARGIN)
        root.Add(wx.StaticLine(self.panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, MARGIN)
        self.panel.SetSizer(root)
        self.panel.SetMinSize((-1, 150))
        self.panel.Bind(wx.EVT_SIZE, self._on_size)
        self.set_step(0, "Review the inputs, then use the primary action.")

    def _on_size(self, event: wx.SizeEvent) -> None:
        width = max(420, event.GetSize().width - 2 * MARGIN)
        self.subtitle.Wrap(width)
        self.next_action.Wrap(width)
        event.Skip()

    def set_step(self, active: int, next_action: str) -> None:
        normal_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE)
        normal_fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT)
        active_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        active_fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT)
        done_bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_INFOBK)
        done_fg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_INFOTEXT)
        for index, label in enumerate(self.labels):
            if index < active:
                background, foreground = done_bg, done_fg
            elif index == active:
                background, foreground = active_bg, active_fg
            else:
                background, foreground = normal_bg, normal_fg
            label.SetBackgroundColour(background)
            label.SetForegroundColour(foreground)
        self.next_action.SetLabel(f"Next: {next_action}")
        self.panel.Layout()


def add_workflow(
    parent: wx.Window,
    sizer: wx.Sizer,
    title: str,
    summary: str,
    steps: Sequence[str],
    help_handler: Callable[[wx.CommandEvent], None] | None = None,
) -> WorkflowGuide:
    guide = WorkflowGuide(parent, title, summary, steps, help_handler)
    sizer.Add(guide.panel, 0, wx.EXPAND)
    return guide


def section(parent: wx.Window, label: str) -> wx.StaticBoxSizer:
    """Create a native KiCad-style grouped section."""
    return wx.StaticBoxSizer(wx.VERTICAL, parent, label)


def mark_primary(button: wx.Button, tooltip: str) -> wx.Button:
    button.SetToolTip(tooltip)
    button.SetDefault()
    return button
