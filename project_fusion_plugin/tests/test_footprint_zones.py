"""Footprint rule areas use world coordinates in boards, local ones in libraries."""
import copy
import importlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_footprint_zones_test'
pkg = ModuleType(PACKAGE); pkg.__path__ = [str(ROOT)]; sys.modules[PACKAGE] = pkg
board = importlib.import_module(PACKAGE + '.board')
repair = importlib.import_module(PACKAGE + '.repair')
sx = importlib.import_module(PACKAGE + '.sexpr')
try:
    import pcbnew
except ImportError:
    pcbnew = None


class FootprintZoneTranslationTests(unittest.TestCase):
    def test_world_contours_and_fill_caches_move_but_local_geometry_does_not(self):
        fp = sx.loads('''(footprint "Example:RuleArea" (at 120 80 90)
          (property "Reference" "R1" (at 0 -2 90))
          (pad "1" smd custom (at -1 0 90) (size .5 .5)
            (primitives (gr_poly (pts (xy -.2 -.2) (xy .2 -.2) (xy .2 .2)))))
          (fp_poly (pts (xy -2 -1) (xy 2 -1) (xy 2 1)))
          (model "body.step" (offset (xyz 1 2 3)))
          (zone (uuid "11111111-1111-4111-8111-111111111111")
            (layer "F.Cu") (hatch edge .5)
            (keepout (tracks allowed) (vias not_allowed) (copperpour not_allowed))
            (polygon (pts (xy 119 79) (xy 121 79) (xy 121 81) (xy 119 81)))
            (filled_polygon (layer "F.Cu")
              (pts (xy 119.1 79.1) (xy 120.9 79.1) (xy 120.9 80.9)))
            (fill_segments (pts (xy 119.2 79.2) (xy 120.8 79.2)))))''')
        original = copy.deepcopy(fp)
        board.translate(fp, -86.5, -32.8)
        self.assertEqual(sx.child(fp, 'at'), ['at', '33.5', '47.2', '90'])
        for tag in ['property', 'pad', 'fp_poly', 'model']:
            self.assertEqual(sx.children(fp, tag), sx.children(original, tag))
        old_zone = sx.child(original, 'zone'); new_zone = sx.child(fp, 'zone')
        for tag in ['uuid', 'layer', 'hatch', 'keepout']:
            self.assertEqual(sx.child(new_zone, tag), sx.child(old_zone, tag))
        before = [n[1:3] for n in sx.walk(old_zone) if sx.tag(n) == 'xy']
        after = [n[1:3] for n in sx.walk(new_zone) if sx.tag(n) == 'xy']
        self.assertEqual(len(before), 9)
        for a, b in zip(before, after):
            self.assertAlmostEqual(float(b[0]) - float(a[0]), -86.5)
            self.assertAlmostEqual(float(b[1]) - float(a[1]), -32.8)


@unittest.skipIf(pcbnew is None, 'Native KiCad Python is required')
class NativeFootprintZoneTests(unittest.TestCase):
    def fixture(self, back=False):
        p = pcbnew; b = p.BOARD(); f = p.FOOTPRINT(b)
        f.SetFPID(p.LIB_ID('Example', 'RuleArea')); f.SetReference('R1'); b.Add(f)
        pad = p.PAD(f); pad.SetNumber('1'); pad.SetAttribute(p.PAD_ATTRIB_SMD)
        pad.SetShape(p.PAD_SHAPE_RECT); pad.SetSize(p.VECTOR2I(p.FromMM(.5), p.FromMM(.5)))
        layers = p.LSET(); layers.AddLayer(p.F_Cu)
        pad.SetLayerSet(layers); pad.SetPosition(p.VECTOR2I(p.FromMM(-1), 0)); f.Add(pad)
        zone = p.ZONE(f); zone.SetLayer(p.F_Cu); zone.SetIsRuleArea(True)
        zone.SetDoNotAllowTracks(False); zone.SetDoNotAllowVias(True); zone.SetDoNotAllowZoneFills(True)
        outline = zone.Outline(); outline.NewOutline()
        for x, y in [(-.4, -.5), (.4, -.5), (.4, .5), (-.4, .5)]:
            outline.Append(p.FromMM(x), p.FromMM(y))
        outline.NewHole()
        for x, y in [(-.1, -.1), (.1, -.1), (.1, .1), (-.1, .1)]:
            outline.Append(p.FromMM(x), p.FromMM(y), 0, 0)
        f.Add(zone)
        if back: f.Flip(f.GetPosition(), False)
        f.SetOrientationDegrees(-90 if back else 90)
        f.SetPosition(p.VECTOR2I(p.FromMM(120), p.FromMM(80)))
        return b, f

    def points(self, zone):
        s = zone.Outline(); points = []
        for i in range(s.OutlineCount()):
            chains = [s.COutline(i)] + [s.CHole(i, j) for j in range(s.HoleCount(i))]
            points.extend((c.CPoint(j).x, c.CPoint(j).y) for c in chains for j in range(c.PointCount()))
        return points

    def test_translation_matches_native_movement_after_file_roundtrip(self):
        p = pcbnew
        for back in [False, True]:
            with self.subTest(back=back), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'board.kicad_pcb'; b, fp = self.fixture(back)
                p.SaveBoard(str(path), b); tree = sx.load(path); f = sx.child(tree, 'footprint')
                local_pads = copy.deepcopy(sx.children(f, 'pad'))
                expected = p.FOOTPRINT(fp)
                units = p.FromMM(1)
                expected.Move(p.VECTOR2I(round(-86.5 * units), round(-32.8 * units)))
                board.translate(f, -86.5, -32.8); sx.save(path, tree)
                self.assertEqual(sx.children(f, 'pad'), local_pads)
                loaded_board = p.LoadBoard(str(path)); actual = next(iter(loaded_board.GetFootprints()))
                self.assertEqual(self.points(next(iter(actual.Zones()))), self.points(next(iter(expected.Zones()))))
                self.assertEqual([(q.GetPosition().x, q.GetPosition().y) for q in actual.Pads()],
                                 [(q.GetPosition().x, q.GetPosition().y) for q in expected.Pads()])
                self.assertEqual(next(iter(actual.Zones())).m_Uuid.AsString(), next(iter(fp.Zones())).m_Uuid.AsString())

    def test_library_freeze_normalizes_zones_without_mutating_placed_footprint(self):
        p = pcbnew
        for back in [False, True]:
            with self.subTest(back=back), tempfile.TemporaryDirectory() as folder:
                b, fp = self.fixture(back); io = p.PCB_IO_KICAD_SEXPR()
                before = self.points(next(iter(fp.Zones())))
                pad_before = [(q.GetPosition().x, q.GetPosition().y) for q in fp.Pads()]
                repair._save_local_footprint(fp, Path(folder), io, p.LIB_ID('Frozen', 'Saved'))
                self.assertEqual(str(fp.GetFPID().GetLibNickname()), 'Example')
                self.assertEqual(str(fp.GetFPID().GetLibItemName()), 'RuleArea')
                self.assertEqual(self.points(next(iter(fp.Zones()))), before)
                self.assertEqual([(q.GetPosition().x, q.GetPosition().y) for q in fp.Pads()], pad_before)
                self.assertEqual((fp.GetPosition().x, fp.GetPosition().y), (p.FromMM(120), p.FromMM(80)))
                loaded = io.FootprintLoad(folder, 'Saved')
                self.assertFalse(fp.FootprintNeedsUpdate(loaded, p.BOARD_ITEM.DRC))
                self.assertTrue(all(abs(x) < p.FromMM(1) and abs(y) < p.FromMM(1)
                                    for x, y in self.points(next(iter(loaded.Zones())))))


if __name__ == '__main__': unittest.main()
