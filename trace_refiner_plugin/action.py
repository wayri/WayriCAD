"""Originating-editor native action for checked trace refinement."""
from pathlib import Path
import pcbnew


class TraceRefinerAction(pcbnew.ActionPlugin):
    def defaults(self):
        self.name='WayriCAD Trace Refiner';self.category='Layout'
        self.description='Preview and validate small trace jog cleanup before applying'
        self.show_toolbar_button=True
        self.icon_file_name=str(Path(__file__).with_name('resources')/'icon-24.png')
        self.dark_icon_file_name=str(Path(__file__).with_name('resources')/'icon-dark-24.png')
    def Run(self):
        import wx
        from .ui import RefinerFrame
        from .refiner import board_identity
        try:
            board=pcbnew.GetBoard()
            if board is None:raise ValueError('Open a PCB in PCB Editor first.')
            existing=getattr(self,'_frame',None)
            if existing and existing.guard():existing.Show();existing.Raise();return
            if existing:existing.Destroy()
            identity=board_identity(board)
            def guard():
                current=pcbnew.GetBoard()
                return current is not None and board_identity(current)==identity
            self._frame=RefinerFrame(wx.GetActiveWindow(),board,guard);self._frame.Show();self._frame.Raise()
        except Exception as exc:wx.MessageBox(str(exc),'Trace Refiner',wx.OK|wx.ICON_ERROR)
