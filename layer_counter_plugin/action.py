"""Launch a counter preview tied to its originating PCB Editor board."""
from pathlib import Path
import pcbnew


class LayerCounterAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name='WayriCAD Layer Counter'
        self.category='Layout'
        self.description='Preview and add a grouped copper layer identification counter'
        self.show_toolbar_button=True
        self.icon_file_name=str(Path(__file__).with_name('resources')/'icon-24.png')
        self.dark_icon_file_name=str(Path(__file__).with_name('resources')/'icon-dark-24.png')

    def Run(self):
        import wx
        from .ui import LayerCounterFrame
        from .core import _board_identity
        try:
            board=pcbnew.GetBoard()
            if board is None:raise ValueError('Open a PCB in PCB Editor first.')
            frame=getattr(self,'_frame',None)
            if frame is not None and frame:
                if frame.board_guard():frame.Show();frame.Raise();return
                frame.Destroy()
            identity=_board_identity(board)
            def guard():
                current=pcbnew.GetBoard()
                return current is not None and _board_identity(current)==identity
            self._frame=LayerCounterFrame(wx.GetActiveWindow(),board,board_guard=guard)
            self._frame.Show();self._frame.Raise()
        except Exception as exc:
            wx.MessageBox(str(exc),self.name,wx.OK|wx.ICON_ERROR)
