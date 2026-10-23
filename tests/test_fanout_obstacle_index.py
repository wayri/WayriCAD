"""Conservative fanout broadphase, including native rotated-pad envelopes."""
import math
import random
import unittest
from types import SimpleNamespace

from wayricad_runtime.routing import _ObstacleIndex
from wayricad_runtime.geometry import segment_hits_pad

try:
    import pcbnew
except ImportError:
    pcbnew = None


def box(left, top, right, bottom):
    return SimpleNamespace(GetLeft=lambda: left, GetTop=lambda: top,
                           GetRight=lambda: right, GetBottom=lambda: bottom)


def point(x, y):
    return SimpleNamespace(x=x, y=y)


class ObstacleIndexTests(unittest.TestCase):
    def test_order_boundary_negative_coordinates_and_large_items(self):
        items = [SimpleNamespace(GetBoundingBox=lambda: box(-5, -5, 0, 0)),
                 SimpleNamespace(GetBoundingBox=lambda: box(-10000, -10000, 10000, 10000)),
                 SimpleNamespace(GetBoundingBox=lambda: box(0, 0, 5, 5)),
                 SimpleNamespace(GetBoundingBox=lambda: box(100, 100, 101, 101))]
        index = _ObstacleIndex(items, cell_size=5)
        self.assertEqual(index.query([point(0, 0)], 0), items[:3])
        self.assertEqual(index.query([], 1), [])
        self.assertEqual(index.query([point(-1000, -1000), point(1000, 1000)], 0), items)

    @unittest.skipIf(pcbnew is None, 'KiCad native Python required')
    def test_native_pad_envelope_has_no_broadphase_false_negatives(self):
        api = pcbnew
        board = api.BOARD()
        fp = api.FOOTPRINT(board)
        board.Add(fp)
        shapes = (api.PAD_SHAPE_RECT, api.PAD_SHAPE_ROUNDRECT,
                  api.PAD_SHAPE_OVAL, api.PAD_SHAPE_CIRCLE)
        randomizer = random.Random(823)
        checked = 0
        for shape in shapes:
            for angle in (0, 23, 45, 90, 179):
                pad = api.PAD(fp)
                pad.SetAttribute(api.PAD_ATTRIB_SMD)
                pad.SetShape(shape)
                pad.SetPosition(api.VECTOR2I(-5_000_000, 5_000_000))
                pad.SetSize(api.VECTOR2I(1_000_000, 1_000_000 if shape == api.PAD_SHAPE_CIRCLE else 3_000_000))
                pad.SetOrientation(api.EDA_ANGLE(angle, api.DEGREES_T))
                pad.SetOffset(api.VECTOR2I(100_000, -200_000))
                fp.Add(pad)
                index = _ObstacleIndex([pad], cell_size=250_000)
                for _ in range(200):
                    start = api.VECTOR2I(-5_000_000+randomizer.randrange(-4_000_000, 4_000_000),
                                        5_000_000+randomizer.randrange(-4_000_000, 4_000_000))
                    end = api.VECTOR2I(start.x+randomizer.randrange(-1_000_000, 1_000_000),
                                      start.y+randomizer.randrange(-1_000_000, 1_000_000))
                    margin = randomizer.randrange(0, 800_000)
                    if segment_hits_pad(start, end, pad, margin, api):
                        self.assertIn(pad, index.query([start, end], math.sqrt(2)*margin))
                        checked += 1
        self.assertGreater(checked, 300)
