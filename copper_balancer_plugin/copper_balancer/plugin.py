from pathlib import Path
import pcbnew


class CopperBalancerPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "WayriCAD Copper Balancer"
        self.category = "PCB manufacturing"
        self.description = "Preview and generate copper thieving and local density balancing"
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).resolve().parents[1] / "resources" / "icon-24.png")

        self.dark_icon_file_name = str(Path(__file__).resolve().parents[1] / "resources" / "icon-dark-24.png")

    def Run(self):
        import wx
        from .dialog import CopperBalancerDialog
        board = pcbnew.GetBoard()
        if board is None:
            wx.MessageBox("Open a PCB before running WayriCAD Copper Balancer.","WayriCAD Copper Balancer",wx.OK|wx.ICON_INFORMATION)
            return
        dialog = CopperBalancerDialog(wx.GetTopLevelParent(wx.GetActiveWindow()) if wx.GetActiveWindow() else None,board)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
            pcbnew.Refresh()
