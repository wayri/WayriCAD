"""Launch placement review for the originating PCB Editor document."""
from pathlib import Path
import pcbnew


class ComponentArrangerAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'WayriCAD Component Arranger'
        self.category = 'Layout'
        self.description = 'Review compact group placement around an anchor footprint'
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).with_name('resources') / 'icon-24.png')
        self.dark_icon_file_name = str(Path(__file__).with_name('resources') / 'icon-dark-24.png')

    def Run(self):
        import wx
        from .native import identity
        from .ui import ArrangerFrame
        try:
            board = pcbnew.GetBoard()
            if board is None:
                raise ValueError('Open a PCB in PCB Editor first.')
            frame = getattr(self, '_frame', None)
            if frame is not None and frame:
                if frame.board_guard():
                    frame.Show(); frame.Raise(); return
                frame.Destroy()
            origin = identity(board)
            def guard():
                current = pcbnew.GetBoard()
                return current is not None and identity(current) == origin
            self._frame = ArrangerFrame(wx.GetActiveWindow(), board, guard)
            self._frame.Show(); self._frame.Raise()
        except Exception as error:
            wx.MessageBox(str(error), self.name, wx.OK | wx.ICON_ERROR)
