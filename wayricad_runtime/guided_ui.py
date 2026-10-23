"""Compact native workflow header, vendored identically into standalone tools."""
from __future__ import annotations
from typing import Callable,Sequence
import wx
from wayricad_runtime.visual_feedback import bitmap, decorate_button

MARGIN=10
CONTROL_GAP=7
ACCENT='#3399cc'


class WorkflowGuide:
    """A single title/status row; detailed guidance stays in local help/tooltips."""
    def __init__(self,parent,title,summary,steps:Sequence[str],help_handler:Callable|None=None):
        self.steps=list(steps);self.labels=[];self.summary=str(summary)
        self.panel=wx.Panel(parent)
        row=wx.BoxSizer(wx.HORIZONTAL)
        heading=wx.StaticText(self.panel,label=title,style=wx.ST_ELLIPSIZE_END)
        heading.SetFont(heading.GetFont().Bold());heading.SetToolTip(self.summary)
        heading.SetMinSize(self.panel.FromDIP((80,-1)))
        row.Add(heading,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.panel.FromDIP(8))
        self.status_icon=wx.StaticBitmap(self.panel,bitmap=bitmap('info',self.panel))
        row.Add(self.status_icon,0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.panel.FromDIP(5))
        self.progress=wx.StaticText(self.panel,label='',style=wx.ST_ELLIPSIZE_END)
        self.progress.SetMinSize(self.panel.FromDIP((85,-1)))
        row.Add(self.progress,1,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,self.panel.FromDIP(8))
        self.next_action=wx.StaticText(self.panel,label='',style=wx.ST_ELLIPSIZE_END)
        self.next_action.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        self.next_action.SetMinSize(self.panel.FromDIP((80,-1)))
        # Retained for callers that keep the original subtitle attribute.
        self.subtitle=wx.StaticText(self.panel,label=self.summary);self.subtitle.Hide()
        if help_handler is not None:
            help_button=wx.Button(self.panel,label='Help',style=wx.BU_EXACTFIT)
            help_button.SetToolTip('Open local usage and troubleshooting help')
            decorate_button(help_button,'help')
            help_button.Bind(wx.EVT_BUTTON,help_handler)
            row.Add(help_button,0,wx.ALIGN_CENTER_VERTICAL)
        outer=wx.BoxSizer(wx.VERTICAL)
        outer.Add(row,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,self.panel.FromDIP(MARGIN))
        outer.Add(self.next_action,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM|wx.TOP,self.panel.FromDIP(MARGIN))
        self.panel.SetSizer(outer)
        self.panel.Bind(wx.EVT_SIZE,self._on_size)
        for name in ('EVT_SYS_COLOUR_CHANGED','EVT_DPI_CHANGED'):
            event=getattr(wx,name,None)
            if event is not None:self.panel.Bind(event,self._refresh_icon)
        self.set_step(0,self.summary)

    def _on_size(self,event):
        self.panel.Layout();event.Skip()

    def _refresh_icon(self,event=None):
        self.status_icon.SetBitmap(bitmap(self._status_role,self.panel))
        if event is not None:event.Skip()

    def set_step(self,active,next_action):
        active=max(0,int(active));count=len(self.steps)
        stage=self.steps[active] if active<count else 'Complete'
        number=f'{active+1}/{count}' if active<count else f'{count}/{count}' if count else 'Complete'
        self.progress.SetLabel(number+' · '+stage if count else stage)
        self.progress.SetToolTip('Current step: '+stage)
        text=str(next_action).strip()
        self._status_role=('error' if text.casefold().startswith(('error','failed','blocked','cannot')) else
                           'warning' if text.casefold().startswith('warning') else
                           'success' if active>=count else
                           'info' if active==0 else 'next')
        self._refresh_icon()
        self.status_icon.SetToolTip(stage+'\n'+text)
        self.next_action.SetLabel(text)
        self.next_action.SetToolTip(stage+'\n'+text)
        self.panel.Layout()



def add_workflow(parent,sizer,title,summary,steps,help_handler=None):
    guide=WorkflowGuide(parent,title,summary,steps,help_handler)
    sizer.Add(guide.panel,0,wx.EXPAND)
    from wayricad_runtime.layout import install_accessibility
    window=wx.GetTopLevelParent(parent)
    install_accessibility(window)
    if help_handler is not None and not getattr(window,'_wayricad_help_shortcut',False):
        window._wayricad_help_shortcut=True
        def help_key(event):
            if event.GetKeyCode()==wx.WXK_F1:help_handler(event)
            else:event.Skip()
        window.Bind(wx.EVT_CHAR_HOOK,help_key)
    return guide


def section(parent,label):return wx.StaticBoxSizer(wx.VERTICAL,parent,label)


def mark_primary(button,tooltip):
    button.SetToolTip(tooltip);decorate_button(button);button.SetDefault();return button
