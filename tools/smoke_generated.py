"""Native KiCad 10 smoke of generated geometry; operates on a new in-memory board."""
import os
from pathlib import Path
import sys
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pcbnew
import wx


def main():
    app=wx.App(False)
    pcbnew.ActionPlugin.register=lambda self:None
    pcbnew.Refresh=lambda:None
    def error(message,*args,**kwargs):raise RuntimeError(message)
    wx.MessageBox=error
    from heater_designer_plugin.heater_designer_plugin import HeaterFrame, copper_layer
    from planar_magnetics_plugin.planar_magnetics_plugin import MagneticsFrame
    assert copper_layer(1,4)==pcbnew.In1_Cu
    for klass,generate in ((HeaterFrame,'generate'),(MagneticsFrame,'analyze')):
        board=pcbnew.BOARD();frame=klass(None,board)
        try:
            getattr(frame,generate)(None)
            assert frame.result is not None
            if klass is MagneticsFrame:assert frame.tabs.GetSelection()==0
            frame.show_pcb(None)
            assert len(list(board.GetTracks()))==0
            frame.commit(None)
            count=len(list(board.GetTracks()));assert count>0
            frame.undo(None);assert len(list(board.GetTracks()))==0
            frame.redo(None);assert len(list(board.GetTracks()))==count
            print(klass.__name__,count,'items: review, apply, undo, redo passed')
        finally:frame.Destroy();wx.Yield()


if __name__=='__main__':
    status=0
    try:main()
    except BaseException:traceback.print_exc();status=1
    finally:sys.stdout.flush();sys.stderr.flush();os._exit(status)
