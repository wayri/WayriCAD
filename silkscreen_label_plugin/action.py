"""Native KiCad action; all geometry changes follow an inspected preview."""
from pathlib import Path
import pcbnew

class SilkscreenAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name='WayriCAD Silkscreen Label Placer'
        self.category='Layout'
        self.description='Arrange visible silk labels with safe spacing and checked guide lines'
        self.show_toolbar_button=True
        self.icon_file_name=str(Path(__file__).with_name('resources')/'icon-24.png')
        self.dark_icon_file_name=str(Path(__file__).with_name('resources')/'icon-dark-24.png')

    def Run(self):
        import wx
        from .ui import SilkscreenFrame
        try:
            board=pcbnew.GetBoard()
            if board is None:raise ValueError('Open a PCB in PCB Editor first.')
            existing=getattr(self,'_frame',None)
            if existing is not None and existing:
                if existing.board_guard():existing.Show();existing.Raise();return
                existing.Destroy()
            identity=int(board.this)
            def current_board():
                current=pcbnew.GetBoard()
                return current is not None and int(current.this)==identity
            self._frame=SilkscreenFrame(wx.GetActiveWindow(),board,board_guard=current_board)
            self._frame.Show();self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(str(exc),self.name,wx.OK|wx.ICON_ERROR)
