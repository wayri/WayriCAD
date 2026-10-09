from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from wayricad_mechanical.label_layout import LabelRequest, layout_labels


def separated(a, b, gap):
    return (a[2] + gap <= b[0] or b[2] + gap <= a[0]
            or a[3] + gap <= b[1] or b[3] + gap <= a[1])


class LabelLayoutTests(unittest.TestCase):
    def assert_legal(self, placed, width, height, margin=4, gap=3, reserved=()):
        rectangles = list(placed.values())
        for rect in rectangles:
            self.assertGreaterEqual(rect[0], margin)
            self.assertGreaterEqual(rect[1], margin)
            self.assertLessEqual(rect[2], width - margin)
            self.assertLessEqual(rect[3], height - margin)
            for obstacle in reserved:
                self.assertTrue(separated(rect, obstacle, gap), (rect, obstacle))
        for index, rect in enumerate(rectangles):
            for other in rectangles[index + 1:]:
                self.assertTrue(separated(rect, other, gap), (rect, other))

    def test_dense_anchors_place_in_both_axes_and_omit_when_full(self):
        requests = [LabelRequest(str(index), (110, 80), (74, 18)) for index in range(100)]
        placed = layout_labels(requests, 220, 160)
        self.assertGreaterEqual(len(placed), 6)
        self.assertLess(len(placed), len(requests))
        self.assertGreater(len({rect[0] for rect in placed.values()}), 1)
        self.assertGreater(len({rect[1] for rect in placed.values()}), 1)
        self.assert_legal(placed, 220, 160)
        self.assertEqual(placed, layout_labels(requests, 220, 160))

    def test_all_corners_stay_inside_viewport(self):
        requests = [LabelRequest(str(index), anchor, (80, 20))
                    for index, anchor in enumerate(((0, 0), (200, 0), (0, 120), (200, 120)))]
        placed = layout_labels(requests, 200, 120)
        self.assertEqual(len(placed), 4)
        self.assert_legal(placed, 200, 120)

    def test_priority_wins_a_single_available_slot_and_ties_keep_order(self):
        requests = [LabelRequest('ordinary', (35, 20), (62, 32)),
                    LabelRequest('selected', (35, 20), (62, 32), priority=10)]
        self.assertEqual(list(layout_labels(requests, 70, 40)), ['selected'])
        requests[1] = LabelRequest('selected', (35, 20), (62, 32))
        self.assertEqual(list(layout_labels(requests, 70, 40)), ['ordinary'])

    def test_reserved_scale_bar_and_dpi_spacing(self):
        reserved = [(8, 8, 160, 64)]
        requests = [LabelRequest(str(index), (85, 25), (60, 22)) for index in range(15)]
        placed = layout_labels(requests, 320, 240, scale=2, reserved=reserved)
        self.assertTrue(placed)
        self.assert_legal(placed, 320, 240, margin=8, gap=6, reserved=reserved)

    def test_resize_recomputes_positions_and_omits_oversized_labels(self):
        requests = [LabelRequest('small', (80, 50), (60, 22)),
                    LabelRequest('large', (80, 50), (160, 22), priority=5)]
        large = layout_labels(requests, 220, 140)
        small = layout_labels(requests, 100, 80)
        self.assertEqual(set(large), {'small', 'large'})
        self.assertEqual(set(small), {'small'})
        self.assert_legal(large, 220, 140)
        self.assert_legal(small, 100, 80)
        self.assertNotEqual(large['small'], small['small'])

    def test_invalid_and_offscreen_requests_are_omitted(self):
        requests = [LabelRequest('zero', (10, 10), (0, 10)),
                    LabelRequest('nan', (float('nan'), 10), (10, 10)),
                    LabelRequest('outside', (-1, 10), (10, 10)),
                    LabelRequest('too_wide', (10, 10), (200, 10)),
                    LabelRequest('valid', (10, 10), (10, 10))]
        self.assertEqual(set(layout_labels(requests, 100, 80)), {'valid'})
        self.assertEqual(layout_labels(requests, 7, 7), {})

    def test_invalid_configuration_is_actionable(self):
        request = LabelRequest('same', (10, 10), (10, 10))
        with self.assertRaisesRegex(ValueError, 'unique'):
            layout_labels([request, request], 100, 80)
        with self.assertRaisesRegex(ValueError, 'scale'):
            layout_labels([], 100, 80, scale=0)
        with self.assertRaisesRegex(ValueError, 'Reserved'):
            layout_labels([], 100, 80, reserved=[(20, 20, 10, 10)])


if __name__ == '__main__':
    unittest.main()
