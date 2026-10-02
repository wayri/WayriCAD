"""KiCad 10 SWIG action-plugin entry point; no open-board mutation."""
from pathlib import Path
import pcbnew

class ProjectFusionAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'Wayri Project Fusion'
        self.category = 'Project management'
        self.description = 'Manage linked project and subsheet imports, review electrical changes and update saved designs'
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).with_name('icon.png'))
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        import wx
        from .gui import FusionDialog
        initial = ''
        try:
            board = pcbnew.GetBoard()
            initial = board.GetFileName() if board else ''
        except Exception:
            pass
        parent = wx.GetActiveWindow()
        dialog = FusionDialog(parent, initial)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()
