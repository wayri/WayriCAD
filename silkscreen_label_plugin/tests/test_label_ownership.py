"""Native regressions for readable reference ownership and safe partial plans."""
import math
import unittest

import test_placement as fixture
from silkscreen_label_plugin import placement

api = fixture.api


@unittest.skipIf(api is None, 'Native KiCad bindings required')
class LabelOwnershipTests(unittest.TestCase):
    setUp = fixture.PlacementTests.setUp

    def courtyard(self, fp, half_width=.6, half_height=.6):
        centre = fp.GetPosition()
        dx, dy = api.FromMM(half_width), api.FromMM(half_height)
        corners = [(centre.x-dx, centre.y-dy), (centre.x+dx, centre.y-dy),
                   (centre.x+dx, centre.y+dy), (centre.x-dx, centre.y+dy)]
        for first, second in zip(corners, corners[1:]+corners[:1]):
            shape = api.PCB_SHAPE(fp)
            shape.SetShape(api.SHAPE_T_SEGMENT)
            shape.SetLayer(api.F_CrtYd)
            shape.SetWidth(api.FromMM(.05))
            shape.SetStart(api.VECTOR2I(*first))
            shape.SetEnd(api.VECTOR2I(*second))
            fp.Add(shape)
        fp.BuildCourtyardCaches()
        return fp.GetCourtyard(api.F_CrtYd).BBox()

    def other_part(self, reference, x, y):
        fp = api.FOOTPRINT(self.board)
        fp.SetReference(reference)
        fp.SetPosition(self.v(x, y))
        self.board.Add(fp)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        pad = api.PAD(fp)
        pad.SetPosition(self.v(x, y))
        pad.SetSize(self.v(.4, .4))
        pad.SetShape(api.PAD_SHAPE_RECT)
        pad.SetAttribute(api.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pad.SMDMask())
        fp.Add(pad)
        return fp

    @staticmethod
    def distance(first, second):
        return math.hypot(max(first.GetLeft()-second.GetRight(),
                              second.GetLeft()-first.GetRight(), 0),
                          max(first.GetTop()-second.GetBottom(),
                              second.GetTop()-first.GetBottom(), 0))

    @staticmethod
    def snapshot(text):
        position, size = text.GetPosition(), text.GetTextSize()
        return (text.GetText(), position.x, position.y, size.x, size.y,
                text.GetTextAngle().AsDegrees(), text.GetTextThickness(),
                text.IsVisible(), text.IsMirrored(), text.IsBold(),
                text.IsItalic(), text.IsKnockout(), text.GetLayer())

    def actual_envelope(self, text):
        glyphs = api.SHAPE_POLY_SET()
        text.TransformTextToPolySet(glyphs, 0, api.FromMM(.001), api.ERROR_OUTSIDE)
        return glyphs.BBox() if glyphs.OutlineCount() else text.GetBoundingBox()

    def test_misassociated_initial_reference_moves_beside_its_owner(self):
        self.fp.SetReference('R1')
        self.pad.SetSize(self.v(.4, .4))
        own_body = self.courtyard(self.fp)
        neighbour = self.other_part('C1', 24.4, 21.5)
        other_body = self.courtyard(neighbour)
        self.text.SetTextSize(self.v(1, 1))
        self.text.SetPosition(self.v(22.4, 21.5))
        old_position = (self.text.GetPosition().x, self.text.GetPosition().y)
        initial = self.actual_envelope(self.text)
        self.assertGreater(self.distance(initial, own_body),
                           self.distance(initial, other_body)+api.FromMM(.2))
        self.assertFalse(initial.Intersects(other_body))
        review = placement.plan(self.board, api, dict(leaders=False))
        self.assertTrue(review.changes)
        placement.apply(self.board, api, review)
        actual = self.actual_envelope(self.text)
        self.assertNotEqual((self.text.GetPosition().x, self.text.GetPosition().y), old_position)
        self.assertLessEqual(self.distance(actual, own_body),
                             self.distance(actual, other_body)+api.FromMM(.2))
        self.assertLessEqual(self.distance(actual, own_body), api.FromMM(2))

    def test_remote_label_uses_clear_exit_when_nearest_exit_is_blocked(self):
        self.fp.SetPosition(self.v(10, 20))
        self.pad.SetPosition(self.v(10, 20))
        self.text.SetPosition(self.v(10, 20))
        body = self.courtyard(self.fp, 1, 1)
        # Neighbours surround the top, right and bottom exits. A left-hand
        # corridor is too short vertically for text but wide enough for a
        # checked guide, reached by routing around the courtyard group.
        rectangles = [(1, 15, 14, 18.6), (1, 21.4, 14, 25),
                      (11.4, 18.6, 14, 21.4),
                      (1, 18.6, 8.6, 19.6), (1, 20.4, 8.6, 21.4)]
        neighbours = []
        for index, (left, top, right, bottom) in enumerate(rectangles):
            fp = self.other_part('J'+str(index+1), (left+right)/2, (top+bottom)/2)
            neighbours.append(self.courtyard(fp, (right-left)/2, (bottom-top)/2))
        known_route = [(17, 14), (.4, 14), (.4, 20), (8.65, 20)]
        for first, second in zip(known_route, known_route[1:]):
            for obstacle in [body, *neighbours]:
                self.assertFalse(placement.segment_hits_box(
                    self.v(*first), self.v(*second), obstacle, api.FromMM(.275)))
        review = placement.plan(self.board, api, dict(allowed_rotations=(0,)))
        self.assertTrue(review.changes)
        change = review.changes[0]
        self.assertTrue(change.leader_path)
        endpoint = change.leader_path[-1]
        self.assertLess(endpoint[0], body.GetLeft())
        self.assertAlmostEqual(api.ToMM(endpoint[1]), 20, delta=.1)
        for first, second in zip(change.leader_path, change.leader_path[1:]):
            for obstacle in neighbours:
                self.assertFalse(placement.segment_hits_box(
                    api.VECTOR2I(*first), api.VECTOR2I(*second), obstacle,
                    api.FromMM(.2)+change.leader[4]//2))
        placement.apply(self.board, api, review)
        actual = self.actual_envelope(self.text)
        self.assertFalse(actual.Intersects(body))
        self.assertTrue(all(not actual.Intersects(obstacle) for obstacle in neighbours))
    def test_visible_glyph_clearance_does_not_reserve_font_padding(self):
        self.fp.SetReference('R260')
        body = self.courtyard(self.fp, 1.2, 1.2)
        review = placement.plan(self.board, api, dict(leaders=False))
        self.assertTrue(review.changes)
        placement.apply(self.board, api, review)
        visible = self.actual_envelope(self.text)
        # The layout rectangle contains font ascent/descent spacing. Native
        # rendered polygons include the actual stroke, so only that envelope
        # needs the full board silk clearance from the reserved courtyard.
        self.assertGreaterEqual(self.distance(visible, body), api.FromMM(.2))
        self.assertFalse(visible.Intersects(body))
        self.assertTrue(self.text.GetBoundingBox().Intersects(body))
        self.assertFalse(visible.Intersects(self.pad.GetBoundingBox()))
    def test_existing_small_reference_is_not_enlarged_to_default_height(self):
        self.board.GetDesignSettings().m_MinSilkTextHeight = api.FromMM(.6)
        self.board.GetDesignSettings().m_MinSilkTextThickness = api.FromMM(.1)
        self.text.SetTextSize(self.v(.8, .8))
        self.text.SetTextThickness(api.FromMM(.12))
        review = placement.plan(self.board, api)
        self.assertTrue(review.changes)
        placement.apply(self.board, api, review)
        self.assertEqual(self.text.GetTextSize().x, api.FromMM(.8))
        self.assertEqual(self.text.GetTextSize().y, api.FromMM(.8))
    def test_known_horizontal_room_wins_over_existing_rotation(self):
        self.courtyard(self.fp, 1.2, 1.2)
        self.text.SetTextAngle(api.EDA_ANGLE(90, api.DEGREES_T))
        review = placement.plan(self.board, api,
                                dict(leaders=False, allowed_rotations=(0, 45, 90)))
        self.assertTrue(review.changes)
        placement.apply(self.board, api, review)
        self.assertEqual(self.text.GetTextAngle().AsDegrees(), 0)
        self.assertLessEqual(self.distance(self.actual_envelope(self.text),
                                          self.fp.GetCourtyard(api.F_CrtYd).BBox()),
                             api.FromMM(2))

    def test_references_only_preserves_manual_board_and_footprint_text(self):
        self.courtyard(self.fp, 1.1, 1.1)
        manual = []
        for parent, content, position in ((self.board, 'KEEP MANUAL', (20, 17.7)),
                                           (self.fp, 'ASSEMBLY NOTE', (16, 20))):
            text = api.PCB_TEXT(parent)
            text.SetText(content)
            text.SetLayer(api.F_SilkS)
            text.SetPosition(self.v(*position))
            text.SetTextSize(self.v(.8, .8))
            text.SetTextThickness(api.FromMM(.12))
            parent.Add(text)
            manual.append(text)
        before = [self.snapshot(text) for text in manual]
        review = placement.plan(self.board, api)
        self.assertEqual(review.stats['eligible'], 1)
        self.assertTrue(review.changes)
        placement.apply(self.board, api, review)
        self.assertEqual(before, [self.snapshot(text) for text in manual])
        moved = self.actual_envelope(self.text)
        for text in manual:
            self.assertFalse(moved.Intersects(self.actual_envelope(text)))

    def test_applied_reference_clears_pad_courtyard_and_concave_outline(self):
        for drawing in list(self.board.GetDrawings()):
            if drawing.GetLayer() == api.Edge_Cuts:
                self.board.Remove(drawing)
        # A deep right-hand notch makes the old label position lie outside.
        boundary = [(0, 0), (40, 0), (40, 14), (24, 14),
                    (24, 26), (40, 26), (40, 40), (0, 40)]
        for first, second in zip(boundary, boundary[1:]+boundary[:1]):
            edge = api.PCB_SHAPE(self.board)
            edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetLayer(api.Edge_Cuts)
            edge.SetStart(self.v(*first))
            edge.SetEnd(self.v(*second))
            self.board.Add(edge)
        self.fp.SetPosition(self.v(22, 20))
        self.pad.SetPosition(self.v(22, 20))
        self.text.SetPosition(self.v(26, 20))
        self.courtyard(self.fp, 1.2, 1.2)
        review = placement.plan(self.board, api, dict(leaders=False))
        self.assertTrue(review.changes)
        placement.apply(self.board, api, review)
        box = self.actual_envelope(self.text)
        self.assertFalse(box.Intersects(self.pad.GetBoundingBox()))
        self.assertFalse(box.Intersects(self.fp.GetCourtyard(api.F_CrtYd).BBox()))
        outline = api.SHAPE_POLY_SET()
        self.assertTrue(self.board.GetBoardPolygonOutlines(outline, False))
        for x in (box.GetLeft(), box.GetRight()):
            for y in (box.GetTop(), box.GetBottom()):
                self.assertTrue(outline.Contains(api.VECTOR2I(x, y)))
        # Independent notch rectangle check catches an envelope spanning the cut.
        notch = api.BOX2I(self.v(24, 14), self.v(16, 12))
        self.assertFalse(box.Intersects(notch))

    def test_unresolved_overlapping_original_is_not_counted_as_accepted(self):
        self.pad.SetSize(self.v(20, 20))
        before = self.snapshot(self.text)
        review = placement.plan(self.board, api, dict(max_radius=.25))
        self.assertFalse(review.changes)
        self.assertEqual(review.stats['placed'], 0)
        self.assertEqual(review.stats['unresolved'], 1)
        self.assertEqual(len(review.rejected), 1)
        self.assertEqual(before, self.snapshot(self.text))
        self.assertTrue(self.actual_envelope(self.text).Intersects(self.pad.GetBoundingBox()))


if __name__ == '__main__':
    unittest.main()
