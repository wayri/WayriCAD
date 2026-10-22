"""Native regressions for readable reference ownership and safe partial plans."""
import math
import unittest

import test_placement as fixture
from silkscreen_label_plugin import placement

api = fixture.api


class EdgeAlignmentTests(unittest.TestCase):
    def test_centred_wide_text_can_spill_past_a_short_edge(self):
        self.assertEqual(placement.edge_alignment((-4,-2,6,-1),(0,0,2,8),.5),(0,0))

    def test_diagonal_label_is_not_in_a_projected_edge_corridor(self):
        self.assertEqual(placement.edge_alignment((-3,-2,-1,-.5),(0,0,4,4),.5)[0],1)

    def test_margin_allows_small_centre_offset_without_changing_clearance(self):
        bounds=(-2,3.9,-1,4.5)
        self.assertEqual(placement.edge_alignment(bounds,(0,0,4,4),.5)[0],0)
        self.assertEqual(placement.edge_alignment(bounds,(0,0,4,4),0)[0],1)


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
        self.assertIn('C1',review.outcomes[0]['before_association_warning'])
        self.assertEqual(review.outcomes[0]['association_warning'],'')
        placement.apply(self.board, api, review)
        actual = self.actual_envelope(self.text)
        self.assertNotEqual((self.text.GetPosition().x, self.text.GetPosition().y), old_position)
        self.assertLessEqual(self.distance(actual, own_body),
                             self.distance(actual, other_body)+api.FromMM(.2))
        self.assertLessEqual(self.distance(actual, own_body), api.FromMM(2))

    def test_enclosed_component_does_not_receive_a_maze_leader(self):
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
        review = placement.plan(self.board, api, dict(body_clearance=.2,allowed_rotations=(0,)))
        # A collision-free multi-bend route exists, but its distant label has
        # no direct sightline. Do not misrepresent that as a resolved label.
        self.assertFalse(review.changes)
        self.assertEqual(review.stats['placed'], 0)
        self.assertEqual(len(review.rejected), 1)

    def test_nearby_reference_reserves_a_straight_unprinted_association(self):
        body=self.courtyard(self.fp)
        review=placement.plan(self.board,api,dict(leaders=False))
        self.assertTrue(review.changes)
        change=review.changes[0]
        self.assertEqual(len(change.sightline),2)
        self.assertFalse(change.leader_path)
        self.assertLessEqual(self.distance(change.box,body),api.FromMM(2))
        self.assertFalse(placement.segment_hits_box(
            api.VECTOR2I(*change.sightline[0]),api.VECTOR2I(*change.sightline[1]),body))

    def test_long_label_is_near_when_its_glyph_edge_is_near(self):
        self.fp.SetReference('TP_LONG_SIGNAL_NAME')
        body=self.courtyard(self.fp,1.2,.6)
        # Only a horizontal channel is free. The text's centre must be more
        # than 2 mm away even though its nearest glyph edge is adjacent.
        for top,bottom in ((0,19.1),(20.9,40)):
            obstacle=api.PCB_SHAPE(self.board)
            obstacle.SetShape(api.SHAPE_T_RECT);obstacle.SetLayer(api.F_SilkS)
            obstacle.SetStart(self.v(0,top));obstacle.SetEnd(self.v(40,bottom))
            obstacle.SetWidth(api.FromMM(.1));self.board.Add(obstacle)
        review=placement.plan(self.board,api,dict(max_radius=2,leaders=False,allowed_rotations=(0,)))
        self.assertEqual(review.stats['placed'],1)
        change=review.changes[0]
        self.assertLessEqual(self.distance(change.box,body),api.FromMM(2))
        self.assertGreater(abs(change.after[0]-self.fp.GetPosition().x),api.FromMM(2))

    def test_wide_reference_centres_on_short_edge_without_requiring_full_text_containment(self):
        self.fp.SetReference('TP_LONG_SIGNAL_NAME')
        body=self.courtyard(self.fp,.6,1.8)
        review=placement.plan(self.board,api,dict(leaders=False,allowed_rotations=(0,)))
        self.assertEqual(review.stats['placed'],1)
        change=review.changes[0]
        self.assertLessEqual(abs(change.box.GetCenter().x-body.GetCenter().x),1)
        self.assertGreater(change.box.GetWidth(),body.GetWidth())
        self.assertLessEqual(self.distance(change.box,body),api.FromMM(2))

    def test_native_edge_centring_handles_rotation_justification_and_input_mirroring(self):
        for angle in (0,90):
            for justification in (api.GR_TEXT_H_ALIGN_LEFT,api.GR_TEXT_H_ALIGN_CENTER,api.GR_TEXT_H_ALIGN_RIGHT):
                for mirror in (False,True):
                    with self.subTest(angle=angle,justification=justification,mirror=mirror):
                        self.setUp()
                        self.pad.SetSize(self.v(.4,.4))
                        body=self.courtyard(self.fp)
                        self.fp.SetReference('R100')
                        self.text.SetTextSize(self.v(.8,.8))
                        self.text.SetTextAngle(api.EDA_ANGLE(angle,api.DEGREES_T))
                        self.text.SetHorizJustify(justification)
                        self.text.SetMirrored(mirror)
                        review=placement.plan(self.board,api,dict(allowed_rotations=(angle,),
                            auto_size=False,height=.8,edge_margin=0))
                        self.assertEqual(review.stats['placed'],1)
                        change=review.changes[0]
                        box=change.box
                        side=box.GetRight()<=body.GetLeft() or box.GetLeft()>=body.GetRight()
                        offset=abs(box.GetCenter().y-body.GetCenter().y) if side else abs(box.GetCenter().x-body.GetCenter().x)
                        self.assertLessEqual(offset,1)
    def test_visible_glyph_clearance_does_not_reserve_font_padding(self):
        self.fp.SetReference('R260')
        body = self.courtyard(self.fp, 1.2, 1.2)
        review = placement.plan(self.board, api, dict(leaders=False,body_clearance=.2))
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
        review = placement.plan(self.board, api, dict(max_radius=.1))
        self.assertFalse(review.changes)
        self.assertEqual(review.stats['placed'], 0)
        self.assertEqual(review.stats['unresolved'], 1)
        self.assertEqual(len(review.rejected), 1)
        self.assertEqual(before, self.snapshot(self.text))
        self.assertTrue(self.actual_envelope(self.text).Intersects(self.pad.GetBoundingBox()))


if __name__ == '__main__':
    unittest.main()
