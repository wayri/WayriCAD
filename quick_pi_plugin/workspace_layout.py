"""Compact result context retained when the optional Details drawer is shut."""
from .workspace_controls import ColorLegend


class WorkspaceLegend(ColorLegend):
    """Keep the visible metric and limits synchronized with live-current colours."""
    def __init__(self,parent,summary):
        super().__init__(parent)
        self.summary=summary

    def set_scale(self,scale):
        super().set_scale(scale)
        if scale:
            low,high=scale['limits']
            text=f"{scale['label']} · {low:.5g} → {high:.5g} {scale['unit']}"
        else:text='Setup → choose net and pads · Run → inspect copper'
        self.summary.SetLabel(text)
        self.summary.SetToolTip(text+' · Details shows the calibrated colour legend and probes.')
