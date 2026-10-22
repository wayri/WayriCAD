"""Native typography, size floors and reversible style placement contracts."""
import unittest
try:
    import pcbnew as api
except ImportError:
    api = None
from silkscreen_label_plugin.placement import plan, apply, fingerprint, _state, _box
from silkscreen_label_plugin.tests.test_placement import dense_board


@unittest.skipIf(api is None, 'KiCad native bindings are required.')
class TypographyTests(unittest.TestCase):
    def board(self, width=30, height=30):
        b = api.BOARD()
        points = [(0,0),(width,0),(width,height),(0,height)]
        for i,p in enumerate(points):
            edge=api.PCB_SHAPE(b); edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetStart(self.v(*p)); edge.SetEnd(self.v(*points[(i+1)%4]))
            edge.SetLayer(api.Edge_Cuts); b.Add(edge)
        return b

    def v(self,x,y):
        return api.VECTOR2I(api.FromMM(x),api.FromMM(y))

    def test_auto_size_fits_bounded_narrow_board_without_crossing_floor(self):
        b=self.board(6,8)
        t=api.PCB_TEXT(b); t.SetText('TP12345'); t.SetPosition(self.v(3,4))
        t.SetLayer(api.F_SilkS); t.SetTextSize(self.v(2,2)); t.SetTextThickness(api.FromMM(.15)); b.Add(t)
        fixed=plan(b,api,dict(references=False,board_text=True,height=2,auto_size=False,
                             allowed_rotations=[0],max_radius=2))
        self.assertEqual(fixed.stats['placed'],0)
        source=fingerprint(b,api)
        sized=plan(b,api,dict(references=False,board_text=True,height=2,
                             auto_size=True,min_height=.7,size_step=.1,
                             allowed_rotations=[0],max_radius=2))
        self.assertEqual(sized.stats['placed'],1)
        change=sized.changes[0]
        self.assertLess(change.after[4],api.FromMM(2))
        self.assertGreaterEqual(change.after[4],b.GetDesignSettings().m_MinSilkTextHeight)
        self.assertGreaterEqual(change.after[5],b.GetDesignSettings().m_MinSilkTextThickness)
        self.assertEqual(source,fingerprint(b,api))
        tx=apply(b,api,sized); tx.undo(); self.assertEqual(source,fingerprint(b,api))

    def test_all_reading_directions_and_both_sides_render_requested_angles(self):
        for bottom in (False,True):
            for rotation in (0,17,45,90,135):
                for direction,offset in (('Bottom/right',0),('Top/left',180)):
                    b=dense_board(api,1,1)
                    fp=next(iter(b.GetFootprints())); fp.SetOrientationDegrees(45); t=fp.Reference()
                    if bottom:
                        fp.SetLayer(api.B_Cu); t.SetLayer(api.B_SilkS)
                    before=_state(t)
                    p=plan(b,api,dict(allowed_rotations=[rotation],reading_direction=direction))
                    tx=apply(b,api,p)
                    self.assertEqual(t.GetTextAngle().AsDegrees()%360,rotation+offset)
                    self.assertEqual(t.GetDrawRotation().AsDegrees()%360,rotation+offset)
                    self.assertEqual(t.IsMirrored(),bottom)
                    self.assertFalse(t.IsKeepUpright())
                    tx.undo(); self.assertEqual(_state(t),before)

    def test_ordered_explicit_styles_and_knockout_envelope(self):
        b=dense_board(api,2,1); fps=sorted(b.GetFootprints(),key=lambda f:f.GetReference())
        fps[0].SetReference('TP1'); fps[1].SetReference('J1'); fps[1].SetValue('Programming')
        rules=[dict(ref_pattern='tp*',knockout=True),
               dict(ref_pattern='J7, J1',value_pattern='*SWD*, program*',bold=True,italic=True,knockout=True)]
        source=fingerprint(b,api)
        p=plan(b,api,dict(formatting_rules=rules))
        self.assertEqual(len(p.changes),2)
        for c in p.changes:
            self.assertTrue(c.after[9])
            self.assertEqual(c.after[7:9],(False,False) if c.item.GetText()=='TP1' else (True,True))
            clone=api.PCB_TEXT(c.item)
            from silkscreen_label_plugin.placement import _set
            _set(clone,c.after,api)
            poly=api.SHAPE_POLY_SET(); clone.TransformTextToPolySet(poly,0,api.FromMM(.001),api.ERROR_OUTSIDE)
            self.assertTrue(poly.OutlineCount())
            self.assertTrue(c.box.Contains(poly.BBox()))
        tx=apply(b,api,p); tx.undo(); self.assertEqual(fingerprint(b,api),source)
        tx.redo(); self.assertTrue(all(c.item.IsKnockout() for c in p.changes))

    def test_unmatched_connector_not_assumed_programming_and_first_match_wins(self):
        b=dense_board(api,1,1); fp=next(iter(b.GetFootprints())); fp.SetReference('J1'); fp.SetValue('Input')
        p=plan(b,api,dict(formatting_rules=[dict(ref_pattern='J*',value_pattern='Program*',bold=True)]))
        self.assertFalse(p.changes[0].after[7])
        p=plan(b,api,dict(formatting_rules=[dict(ref_pattern='J1',bold=False),dict(ref_pattern='J*',bold=True)]))
        self.assertFalse(p.changes[0].after[7])

    def test_stale_style_or_keepupright_rejects_apply(self):
        b=dense_board(api,1,1); t=next(iter(b.GetFootprints())).Reference()
        for setter in (lambda:t.SetIsKnockout(not t.IsKnockout()),
                       lambda:t.SetKeepUpright(not t.IsKeepUpright())):
            p=plan(b,api); setter()
            with self.assertRaisesRegex(ValueError,'Board changed'):
                apply(b,api,p)

    def test_custom_stroke_survives_bold_apply_and_undo(self):
        b=dense_board(api,1,1); t=next(iter(b.GetFootprints())).Reference()
        t.SetTextThickness(api.FromMM(.15)); before=_state(t)
        preview=plan(b,api,dict(auto_size=True,formatting_rules=[dict(ref_pattern='*',bold=True,italic=True,knockout=True)]))
        self.assertTrue(preview.changes)
        tx=apply(b,api,preview)
        self.assertEqual(_state(t),preview.changes[0].after)
        tx.undo();self.assertEqual(_state(t),before)
        tx.redo();self.assertEqual(_state(t),preview.changes[0].after)

    def test_common_horizontal_wins_over_existing_rotation(self):
        b=dense_board(api,1,1);t=next(iter(b.GetFootprints())).Reference()
        t.SetTextAngle(api.EDA_ANGLE(90,api.DEGREES_T))
        source=fingerprint(b,api);review=plan(b,api)
        self.assertEqual(len(review.changes),1)
        self.assertEqual(review.changes[0].after[2],0)
        self.assertEqual(source,fingerprint(b,api))

    def test_automatic_correction_preserves_condensed_text_proportions(self):
        b=dense_board(api,1,1);t=next(iter(b.GetFootprints())).Reference()
        t.SetTextSize(self.v(.7,.8))
        review=plan(b,api)
        self.assertTrue(review.changes)
        change=review.changes[0]
        self.assertEqual(change.after[3],api.FromMM(.7))
        self.assertEqual(change.after[4],api.FromMM(.8))
        apply(b,api,review)
        self.assertEqual(t.GetTextSize(),self.v(.7,.8))

    def test_angle_preference_and_custom_angles(self):
        from silkscreen_label_plugin.placement import _angles,DEFAULTS
        options=dict(DEFAULTS,allowed_rotations=[17,90,45,0,135])
        self.assertEqual(_angles(options,90),[0,90,45,135,17])
        options['allowed_rotations']=[17]
        self.assertEqual(_angles(options,0),[17])

    def test_nearby_smaller_horizontal_precedes_distant_large_text(self):
        b=self.board(30,30)
        for left,right in ((0,12),(18,30)):
            obstacle=api.PCB_SHAPE(b);obstacle.SetLayer(api.F_SilkS)
            obstacle.SetShape(api.SHAPE_T_RECT);obstacle.SetStart(self.v(left,10));obstacle.SetEnd(self.v(right,20))
            obstacle.SetWidth(api.FromMM(.1));b.Add(obstacle)
        t=api.PCB_TEXT(b);t.SetText('TP12345');t.SetPosition(self.v(15,15));t.SetLayer(api.F_SilkS)
        t.SetTextSize(self.v(2,2));t.SetTextThickness(api.FromMM(.15));b.Add(t)
        review=plan(b,api,dict(references=False,board_text=True,height=2,min_height=.7,size_step=.1,max_radius=10))
        self.assertEqual(len(review.changes),1)
        change=review.changes[0]
        self.assertEqual(change.after[2],0)
        self.assertLess(change.after[4],api.FromMM(2))
        self.assertLessEqual(((change.after[0]-t.GetPosition().x)**2+(change.after[1]-t.GetPosition().y)**2)**.5,api.FromMM(2))

    def test_invalid_settings_are_rejected_without_mutation(self):
        b=dense_board(api,1,1); source=fingerprint(b,api)
        cases=[dict(allowed_rotations=[]),dict(allowed_rotations=[180]),
               dict(reading_direction='Unknown'),dict(auto_size=True,min_height=2,height=1),
               dict(formatting_rules=[dict(bold=True)]),dict(formatting_rules=[dict(ref_pattern='TP*',bold='yes')])]
        for settings in cases:
            with self.assertRaises(ValueError): plan(b,api,settings)
            self.assertEqual(source,fingerprint(b,api))


if __name__=='__main__': unittest.main()


