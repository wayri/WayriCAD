from __future__ import annotations
from typing import Callable, Sequence
import wx

class WorkflowGuide:
    def __init__(self,parent,title,summary,steps:Sequence[str],help_handler:Callable|None=None):
        self.panel=wx.Panel(parent);root=wx.BoxSizer(wx.VERTICAL);head=wx.BoxSizer(wx.HORIZONTAL)
        label=wx.StaticText(self.panel,label=title);label.SetFont(label.GetFont().Bold().Larger());head.Add(label,1,wx.ALIGN_CENTER_VERTICAL)
        if help_handler:
            button=wx.BitmapButton(self.panel,bitmap=wx.ArtProvider.GetBitmap(wx.ART_HELP,wx.ART_BUTTON,(20,20)));button.SetToolTip("Open integrated help");button.Bind(wx.EVT_BUTTON,help_handler);head.Add(button)
        root.Add(head,0,wx.EXPAND|wx.ALL,10);root.Add(wx.StaticText(self.panel,label=summary),0,wx.EXPAND|wx.LEFT|wx.RIGHT,10);row=wx.BoxSizer(wx.HORIZONTAL);self.labels=[]
        for i,step in enumerate(steps,1):
            item=wx.StaticText(self.panel,label=f" {i}  {step} ",style=wx.ALIGN_CENTER|wx.BORDER_SIMPLE);item.SetMinSize((116,30));row.Add(item,1,wx.RIGHT,6);self.labels.append(item)
        root.Add(row,0,wx.EXPAND|wx.ALL,10);self.next_action=wx.StaticText(self.panel);root.Add(self.next_action,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,10);root.Add(wx.StaticLine(self.panel),0,wx.EXPAND|wx.LEFT|wx.RIGHT,10);self.panel.SetSizer(root);self.panel.SetMinSize((-1,145));self.set_step(0,"Define geometry and electrical inputs, then generate the exact copper preview.")
    def set_step(self,active,next_action):
        for i,label in enumerate(self.labels):
            label.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT if i==active else wx.SYS_COLOUR_INFOBK if i<active else wx.SYS_COLOUR_BTNFACE));label.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT if i==active else wx.SYS_COLOUR_BTNTEXT))
        self.next_action.SetLabel("Next: "+next_action);self.panel.Layout()
def add_workflow(parent,sizer,title,summary,steps,help_handler=None):
    guide=WorkflowGuide(parent,title,summary,steps,help_handler);sizer.Add(guide.panel,0,wx.EXPAND);return guide
