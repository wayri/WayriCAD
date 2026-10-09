"""Native sizing/navigation acceptance for the compact saved-board workspace."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None

_app=None


def portrait_board(path):
    """Disposable portrait PCB with real outlines, footprints and routed context."""
    board=pcbnew.BOARD();net=pcbnew.NETINFO_ITEM(board,'5V_DEMO',1);board.Add(net)
    def position(x,y):return pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))
    for a,b in [((5,5),(80,5)),((80,5),(80,105)),((80,105),(5,105)),((5,105),(5,5))]:
        edge=pcbnew.PCB_SHAPE(board);edge.SetShape(pcbnew.SHAPE_T_SEGMENT);edge.SetStart(position(*a));edge.SetEnd(position(*b));edge.SetLayer(pcbnew.Edge_Cuts);edge.SetWidth(pcbnew.FromMM(.15));board.Add(edge)
    for index,(x,y) in enumerate([(18,18),(65,18),(25,38),(58,38),(25,62),(58,62),(18,88),(65,88)],1):
        footprint=pcbnew.FOOTPRINT(board);footprint.SetReference('U'+str(index));footprint.SetPosition(position(x,y))
        for number,dx in [('1',-2),('2',2)]:
            pad=pcbnew.PAD(footprint);pad.SetNumber(number);pad.SetShape(pcbnew.PAD_SHAPE_RECT);pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetSize(position(2,3));pad.SetLayerSet(pcbnew.LSET.FrontMask());pad.SetPosition(position(x+dx,y));pad.SetNetCode(1);footprint.Add(pad)
        for a,b in [((-5,-5),(5,-5)),((5,-5),(5,5)),((5,5),(-5,5)),((-5,5),(-5,-5))]:
            outline=pcbnew.PCB_SHAPE(footprint);outline.SetShape(pcbnew.SHAPE_T_SEGMENT);outline.SetStart(position(x+a[0],y+a[1]));outline.SetEnd(position(x+b[0],y+b[1]));outline.SetLayer(pcbnew.F_SilkS);outline.SetWidth(pcbnew.FromMM(.15));footprint.Add(outline)
        board.Add(footprint)
        track=pcbnew.PCB_TRACK(board);track.SetStart(position(x-2,y));track.SetEnd(position(10,y));track.SetWidth(pcbnew.FromMM(.6));track.SetNetCode(1);track.SetLayer(pcbnew.F_Cu);board.Add(track)
    pcbnew.SaveBoard(str(path),board)


def portrait_result():
    from quick_pi_plugin.tests.test_solver import strip
    from quick_pi_plugin.solver import solve
    mesh,source,sink=strip(length=65,width=90,nx=13,ny=18)
    mesh['triangle_layer']=[0]*len(mesh['triangles'])
    mesh['points_mm']=[[x+10,y+10,z] for x,y,z in mesh['points_mm']]
    geometry={'net':'5V_DEMO','layers':[{'id':0,'name':'F.Cu','polygons':[{'outer':[[10,10],[75,10],[75,100],[10,100]],'holes':[]}]}],
              'terminals':[{'id':'A','label':'Source rail','polygons':{'0':[{'outer':[[10,10],[10.1,10],[10.1,100],[10,100]],'holes':[]}]}},
                           {'id':'B','label':'Load rail','polygons':{'0':[{'outer':[[74.9,10],[75,10],[75,100],[74.9,100]],'holes':[]}]}}],'vias':[]}
    mesh['geometry']=geometry
    return {'mesh':mesh,'geometry':geometry,'result':solve(mesh,source,sink,source_voltage=5,sink_current=2),
            'request':{'net':'5V_DEMO','source_terminal':'A','sink_terminal':'B'}}


@unittest.skipIf(wx is None,'native KiCad wx runtime required')
class WorkspaceTests(unittest.TestCase):
    def test_viewport_resize_panels_and_navigation_preserve_results(self):
        global _app
        _app=wx.GetApp() or wx.App(False);app=_app
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'demo-power-board.kicad_pcb';portrait_board(path)
            original=hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,str(path))
                try:
                    frame.net.Set(['5V_DEMO']);frame.net.SetValue('5V_DEMO');frame._terminals=[{'id':'A','label':'Source rail'},{'id':'B','label':'Load rail'}]
                    for choice,selection in ((frame.source,0),(frame.sink,1)):choice.Set(['Source rail','Load rail']);choice.SetSelection(selection)
                    frame.voltage.ChangeValue('5');frame.current.ChangeValue('2')
                    data=portrait_result();data['geometry']['source_sha256']=original
                    frame._accept_result(data,data['request'],'solve');frame.Show();frame.Maximize(False)
                    self.assertIsNotNone(frame.color_legend.scale)
                    self.assertIn('mV',frame.color_legend.scale['unit'])
                    contours=[item for item in frame.views[2][0].axes[0].patches if str(item.get_gid()).startswith('board-context:footprint:')]
                    self.assertGreaterEqual(len(contours),32)
                    def settle():
                        app.Yield();frame.main_panel.Layout();app.Yield();frame.views[2][1].draw()
                    for size in ((1320,860),(1000,680),(960,600)):
                        frame.SetSize(size);settle()
                        canvas=frame.views[2][1];height=frame.main_panel.GetClientSize().height
                        self.assertGreater(canvas.GetClientSize().height,.78*height)
                        self.assertGreater(canvas.GetClientSize().width,.42*frame.main_panel.GetClientSize().width)
                        self.assertLessEqual(frame.setup_panel.GetSize().width,frame.FromDIP(245))
                        self.assertTrue(frame.run.IsShownOnScreen())
                        axes=frame.views[2][0].axes[0];self.assertFalse(axes.axison)
                        self.assertGreater(axes.get_position().width,.97);self.assertGreater(axes.get_position().height,.97)
                    before=canvas.GetSize().width
                    frame.setup_toggle.SetValue(False);frame._toggle_setup();frame.inspector_toggle.SetValue(False);frame._toggle_inspector();settle()
                    self.assertFalse(frame.splitter.IsSplit());self.assertGreater(canvas.GetSize().width,before+frame.FromDIP(400))
                    self.assertGreater(canvas.GetSize().width,.95*frame.main_panel.GetClientSize().width)
                    frame.setup_toggle.SetValue(True);frame._toggle_setup();frame.inspector_toggle.SetValue(True);frame._toggle_inspector();settle()
                    self.assertTrue(frame.splitter.IsSplit())
                    frame.options.Collapse(False);frame.console.Collapse(False);frame._layout_inputs();settle()
                    self.assertGreater(canvas.GetClientSize().height,.78*frame.main_panel.GetClientSize().height)
                    self.assertGreater(frame.inputs.GetVirtualSize().height,frame.inputs.GetClientSize().height)
                    frame.options.Collapse(True);frame.console.Collapse(True);frame._layout_inputs()
                    axes=frame.views[2][0].axes[0];frame._navigate('fit');canvas.draw();home=axes.get_xlim()
                    frame._navigate('zoom',.8);canvas.draw();self.assertAlmostEqual(axes.get_xlim()[1]-axes.get_xlim()[0],.8*(home[1]-home[0]))
                    frame.field_style.SetSelection(1);frame._draw(preserve=True);canvas.draw()
                    self.assertAlmostEqual(frame.views[2][0].axes[0].get_xlim()[1]-frame.views[2][0].axes[0].get_xlim()[0],.8*(home[1]-home[0]))
                    frame.book.SetSelection(3);settle();self.assertFalse(frame.setup_panel.IsShown());self.assertFalse(frame.splitter.IsSplit())
                    frame.book.SetSelection(2);settle();self.assertTrue(frame.setup_panel.IsShown());self.assertTrue(frame.splitter.IsSplit())
                    self.assertIs(frame.bundle['result'],data['result']);self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
                    capture=os.environ.get('WAYRICAD_PI_WORKSPACE_CAPTURE')
                    if capture:
                        frame.SetSize((1320,860));frame.field_style.SetSelection(0);frame._draw();frame._navigate('fit');settle();frame.Raise()
                        frame.Refresh();frame.Update();canvas.draw();app.Yield()
                        width,height=frame.main_panel.GetClientSize();bitmap=wx.Bitmap(width,height);dc=wx.MemoryDC(bitmap)
                        self.assertTrue(dc.Blit(0,0,width,height,wx.ClientDC(frame.main_panel),0,0));dc.SelectObject(wx.NullBitmap)
                        self.assertTrue(bitmap.SaveFile(capture,wx.BITMAP_TYPE_PNG))
                finally:
                    frame._end();app.Yield()


if __name__=='__main__':unittest.main()
