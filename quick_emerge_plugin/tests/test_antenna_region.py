"""Actual saved-copper antenna-region fixture and immutable extraction."""
from pathlib import Path
import unittest

try:
    import pcbnew
except ImportError:
    pcbnew = None

from quick_emerge_plugin.pcb_regions import collect_regions
from quick_emerge_plugin.region_ports import plan_region


@unittest.skipIf(pcbnew is None, 'Native KiCad pcbnew required')
class AntennaRegionTests(unittest.TestCase):
    def test_real_copper_crop_has_one_feed_and_preserves_the_larger_board(self):
        path = Path(__file__).with_name('fixtures')/'antenna_region.kicad_pcb'
        before = path.read_bytes()
        board = pcbnew.LoadBoard(str(path))
        area = next(zone for zone in board.Zones() if zone.GetIsRuleArea())
        self.assertFalse(any((area.GetDoNotAllowTracks(), area.GetDoNotAllowPads(),
                              area.GetDoNotAllowVias(), area.GetDoNotAllowZoneFills(),
                              area.GetDoNotAllowFootprints())))
        listing = collect_regions(path)
        self.assertEqual([row['name'] for row in listing['areas']], ['Antenna region'])
        snapshot = collect_regions(path, listing['areas'][0]['id'])
        plan = plan_region(snapshot, 'SIGNAL', 'GND')
        self.assertEqual(plan['blockers'], [])
        self.assertEqual(len(plan['ports']), 1)
        self.assertAlmostEqual(plan['ports'][0]['width_mm'], 2)
        self.assertAlmostEqual(plan['substrate']['thickness_mm'], 1.53)
        self.assertEqual({(row['layer'],row['net']) for row in plan['copper']},
                         {('F.Cu','SIGNAL'),('B.Cu','GND')})
        signal = next(row for row in plan['copper'] if row['net']=='SIGNAL')
        points = [point for shape in signal['polygons'] for point in shape['outer_mm']]
        self.assertAlmostEqual(min(point[0] for point in points), 50)
        self.assertAlmostEqual(max(point[0] for point in points), 90)
        bounds = board.GetBoardEdgesBoundingBox()
        self.assertAlmostEqual(pcbnew.ToMM(bounds.GetWidth()), 100, delta=.1)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
