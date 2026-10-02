"""Native saved-board preview geometry and placement checks (KiCad Python)."""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_preview_test'
pkg = ModuleType(PACKAGE); pkg.__path__ = [str(ROOT)]; sys.modules[PACKAGE] = pkg

try:
    import pcbnew as p
    import wx
except ImportError:
    p = None

if p is not None:
    preview = importlib.import_module(PACKAGE + '.preview')


@unittest.skipIf(p is None, 'KiCad native Python and wxPython required')
class PreviewGeometryTests(unittest.TestCase):
    def make_board(self, folder):
        board = p.BOARD()
        track = p.PCB_TRACK(board)
        track.SetStart(p.VECTOR2I(p.FromMM(10), p.FromMM(20)))
        track.SetEnd(p.VECTOR2I(p.FromMM(20), p.FromMM(20)))
        track.SetWidth(p.FromMM(.4)); track.SetLayer(p.F_Cu); board.Add(track)
        via = p.PCB_VIA(board)
        via.SetPosition(p.VECTOR2I(p.FromMM(20), p.FromMM(20)))
        via.SetWidth(p.FromMM(.9)); via.SetDrill(p.FromMM(.4))
        via.SetLayerPair(p.F_Cu, p.B_Cu); board.Add(via)
        fp = p.FOOTPRINT(board)
        fp.SetFPID(p.LIB_ID('Example', 'Preview'))
        fp.SetReference('R1'); board.Add(fp)
        pad = p.PAD(fp); pad.SetNumber('1'); pad.SetAttribute(p.PAD_ATTRIB_SMD)
        pad.SetShape(p.PAD_SHAPE_RECT)
        pad.SetSize(p.VECTOR2I(p.FromMM(2), p.FromMM(1)))
        layers = p.LSET(); layers.AddLayer(p.F_Cu)
        pad.SetLayerSet(layers); fp.Add(pad)
        fp.SetPosition(p.VECTOR2I(p.FromMM(14), p.FromMM(22)))
        edge = p.PCB_SHAPE(board)
        edge.SetShape(p.SHAPE_T_SEGMENT)
        edge.SetStart(p.VECTOR2I(p.FromMM(8), p.FromMM(18)))
        edge.SetEnd(p.VECTOR2I(p.FromMM(24), p.FromMM(18)))
        edge.SetLayer(p.Edge_Cuts); board.Add(edge)
        zone = p.ZONE(board); zone.SetLayer(p.F_Cu)
        outline = zone.Outline(); outline.NewOutline()
        for x, y in [(11, 24), (18, 24), (18, 28), (11, 28)]:
            outline.Append(p.FromMM(x), p.FromMM(y))
        board.Add(zone)
        path = Path(folder) / 'preview.kicad_pcb'
        p.SaveBoard(str(path), board)
        return path

    def source(self, path, shift=(30, -5)):
        return SimpleNamespace(pcb_file=path, hashes={str(path): hashlib.sha256(path.read_bytes()).hexdigest()},
                               alias='ModuleA', translation=shift, layer_map={'F.Cu': 'In1.Cu'},
                               copper_layers=['F.Cu', 'B.Cu'])

    def test_native_geometry_and_rigid_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_board(folder)
            items, status = preview.extract_board(self.source(path))
            self.assertEqual(status, 'PCB geometry loaded')
            self.assertTrue(any(i.kind == 'line' and i.layer == 'In1.Cu' and
                                i.points == ((40, 15), (50, 15)) and abs(i.width-.4)<1e-6
                                for i in items))
            self.assertTrue(any(i.kind == 'polygon' and i.layer == 'In1.Cu' and
                                min(x for x, y in i.points) < 44 < max(x for x, y in i.points)
                                for i in items))
            self.assertTrue(any(i.kind == 'circle' and i.layer == 'Hole' and
                                i.points == ((50, 15),) for i in items))
            self.assertTrue(any(i.kind == 'zone_outline' and i.layer == 'In1.Cu'
                                for i in items))
            self.assertTrue(any(i.kind == 'line' and i.layer == 'Edge.Cuts' and
                                i.points == ((38, 13), (54, 13)) for i in items))
            # A second instance of the same board reuses parsed native geometry
            # but must receive its own alias and placement.
            second = self.source(path, (-3, 4)); second.alias = 'ModuleB'
            repeated, status = preview.extract_board(second)
            self.assertEqual(status, 'PCB geometry loaded')
            self.assertTrue(any(i.kind == 'line' and i.layer == 'In1.Cu' and
                                i.alias == 'ModuleB' and i.points == ((7, 24), (17, 24))
                                for i in repeated))

    def test_stale_board_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_board(folder)
            source = self.source(path)
            path.write_bytes(path.read_bytes() + b'\n')
            items, status = preview.extract_board(source)
            self.assertEqual(items, [])
            self.assertIn('changed since analysis', status)

    def test_paint_keeps_track_in_zone_void_and_fills_via_annulus(self):
        created_app = wx.GetApp() is None
        app = wx.App(False) if created_app else wx.GetApp()
        bitmap = wx.Bitmap(120, 120)
        dc = wx.MemoryDC(bitmap)
        pmt = preview.Primitive
        fake = SimpleNamespace(
            boxes=[('A', 0, 0, 20, 20)], statuses={}, scale=4, selected_alias=None,
            layer=None, center=(10, 10),
            primitives=[
                pmt('A', 'F.Cu', 'zone_polygon', ((2,2),(18,2),(18,18),(2,18))),
                pmt('A', 'F.Cu', 'zone_polygon', ((5,5),(15,5),(15,15),(5,15)), hole=True),
                pmt('A', 'F.Cu', 'line', ((0,10),(20,10)), 1),
                pmt('A', 'F.Cu', 'circle', ((10,10),), 4, filled=True),
                pmt('A', 'Hole', 'circle', ((10,10),), 1, hole=True),
            ],
            GetClientSize=lambda: wx.Size(120,120),
            _screen=lambda point: (round(20+point[0]*4), round(20+point[1]*4)),
        )
        with mock.patch.object(wx, 'AutoBufferedPaintDC', return_value=dc):
            preview.PlacementPreview.on_paint(fake, None)
        dc.SelectObject(wx.NullBitmap)
        image = bitmap.ConvertToImage()
        copper = (210, 70, 65)
        rgb = lambda x,y: (image.GetRed(x,y), image.GetGreen(x,y), image.GetBlue(x,y))
        self.assertEqual(rgb(44,60), copper)  # track through zone void
        self.assertEqual(rgb(66,60), copper)  # filled via annulus
        self.assertNotEqual(rgb(60,60), copper)  # drilled center
        if created_app:
            del app


if __name__ == '__main__':
    unittest.main()
