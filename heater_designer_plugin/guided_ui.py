"""Compact native workflow header, vendored identically into standalone tools."""
from __future__ import annotations
from typing import Callable,Sequence
import wx

MARGIN=10
CONTROL_GAP=7
ACCENT='#3399cc'


class WorkflowGuide:
    """A single title/status row; detailed guidance stays in local help/tooltips."""
    def __init__(self,parent,title,summary,steps:Sequence[str],help_handler:Callable|None=None):
        self.steps=list(steps);self.labels=[];self.summary=str(summary)
        self.panel=wx.Panel(parent)
        row=wx.BoxSizer(wx.HORIZONTAL)
        heading=wx.StaticText(self.panel,label=title)
        heading.SetFont(heading.GetFont().Bold());heading.SetToolTip(self.summary)
        row.Add(heading,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.panel.FromDIP(16))
        self.next_action=wx.StaticText(self.panel,label='',style=wx.ST_ELLIPSIZE_END)
        self.next_action.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        self.next_action.SetMinSize(self.panel.FromDIP((120,-1)))
        row.Add(self.next_action,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.panel.FromDIP(8))
        # Kept as hidden controls for callers that retain the original attributes.
        self.subtitle=wx.StaticText(self.panel,label=self.summary);self.subtitle.Hide()
        self.progress=wx.StaticText(self.panel,label='');self.progress.Hide()
        if help_handler is not None:
            help_button=wx.Button(self.panel,label='Help',style=wx.BU_EXACTFIT)
            help_button.SetToolTip('Open local usage and troubleshooting help')
            help_button.Bind(wx.EVT_BUTTON,help_handler)
            row.Add(help_button,0,wx.ALIGN_CENTER_VERTICAL)
        outer=wx.BoxSizer(wx.VERTICAL)
        outer.Add(row,0,wx.EXPAND|wx.ALL,self.panel.FromDIP(MARGIN))
        self.panel.SetSizer(outer)
        self.panel.Bind(wx.EVT_SIZE,self._on_size)
        self.set_step(0,self.summary)

    def _on_size(self,event):
        self.panel.Layout();event.Skip()

    def set_step(self,active,next_action):
        active=max(0,int(active))
        stage=self.steps[active] if active<len(self.steps) else 'Complete'
        self.progress.SetLabel(stage)
        text=str(next_action).strip()
        self.next_action.SetLabel(text)
        self.next_action.SetToolTip(stage+'\n'+text)
        self.panel.Layout()


def add_workflow(parent,sizer,title,summary,steps,help_handler=None):
    guide=WorkflowGuide(parent,title,summary,steps,help_handler)
    sizer.Add(guide.panel,0,wx.EXPAND)
    return guide


def section(parent,label):return wx.StaticBoxSizer(wx.VERTICAL,parent,label)


def mark_primary(button,tooltip):
    button.SetToolTip(tooltip);button.SetDefault();return button
