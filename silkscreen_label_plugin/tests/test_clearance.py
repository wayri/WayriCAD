"""Courtyard exclusion and board-scale native text preview regressions."""
import unittest
from unittest.mock import patch, MagicMock
import test_placement as fixture
from silkscreen_label_plugin import placement
api=fixture.api


@unittest.skipIf(api is None,'Native KiCad required')
class ClearanceTests(unittest.TestCase):
    setUp=fixture.PlacementTests.setUp
    def courtyard(self,layer,size=6,closed=True):
        corners=[(20-size/2,20-size/2),(20+size/2,20-size/2),
                 (20+size/2,20+size/2),(20-size/2,20+size/2)]
        shapes=[]
        for i in range(4 if closed else 3):
            shape=api.PCB_SHAPE(self.fp);shape.SetShape(api.SHAPE_T_SEGMENT)
            shape.SetStart(self.v(*corners[i]));shape.SetEnd(self.v(*corners[(i+1)%4]))
            shape.SetLayer(layer);shape.SetWidth(api.FromMM(.05));self.fp.Add(shape);shapes.append(shape)
        return shapes

    def assert_legal_applied(self,preview):
        self.assertTrue(preview.changes)
        placement.apply(self.board,api,preview)
        for change in preview.changes:
            native=api.SHAPE_POLY_SET();change.item.TransformTextToPolySet(native,0,api.FromMM(.001),api.ERROR_OUTSIDE)
            self.assertTrue(native.OutlineCount())
            actual=native.BBox()
            self.assertTrue(change.box.Contains(actual))
            expanded=placement._inflate(actual,api.FromMM(.2),api)
            for fp in self.board.GetFootprints():
                env=placement.courtyard_envelopes(fp,api)
                if change.item.GetLayer() in env:self.assertFalse(expanded.Intersects(env[change.item.GetLayer()]))
                for pad in fp.Pads():
                    if pad.IsOnLayer(api.F_Mask if change.item.GetLayer()==api.F_SilkS else api.B_Mask):
                        self.assertFalse(expanded.Intersects(pad.GetBoundingBox()))

    def test_cold_courtyard_cache_and_both_board_faces_are_reserved(self):
        self.courtyard(api.F_CrtYd,8);self.courtyard(api.B_CrtYd,12)
        before=placement.fingerprint(self.board,api)
        preview=placement.plan(self.board,api)
        self.assertEqual(before,placement.fingerprint(self.board,api))
        self.assert_legal_applied(preview)
        self.text.SetLayer(api.B_SilkS);self.text.SetPosition(self.v(20,20))
        self.assert_legal_applied(placement.plan(self.board,api,dict(leaders=False)))

    def test_open_courtyard_still_reserves_the_whole_drawn_extent(self):
        self.courtyard(api.F_CrtYd,10,closed=False)
        self.assert_legal_applied(placement.plan(self.board,api))

    def test_courtyard_is_not_relaxed_to_force_a_dense_fit(self):
        self.courtyard(api.F_CrtYd,12)
        before=placement.fingerprint(self.board,api)
        # Distance is measured beyond the body. Less than half a glyph plus
        # clearance leaves no legal slot even when guide routing succeeds.
        preview=placement.plan(self.board,api,dict(max_radius=.25))
        self.assertFalse(preview.changes);self.assertTrue(preview.rejected)
        self.assertEqual(before,placement.fingerprint(self.board,api))

    def test_default_sizing_caps_an_existing_oversized_label(self):
        self.text.SetTextSize(self.v(3,3))
        preview=placement.plan(self.board,api)
        self.assertTrue(preview.settings['auto_size'])
        self.assertTrue(preview.changes)
        self.assertLessEqual(preview.changes[0].size[1],api.FromMM(placement.DEFAULTS['height']))
        self.assertGreaterEqual(preview.changes[0].size[1],self.board.GetDesignSettings().m_MinSilkTextHeight)

    def test_native_applied_envelope_mismatch_rolls_back(self):
        preview=placement.plan(self.board,api)
        before=placement.fingerprint(self.board,api)
        preview.changes[0].box=api.BOX2I(self.v(0,0),self.v(.01,.01))
        with self.assertRaisesRegex(ValueError,'reviewed envelope'):
            placement.apply(self.board,api,preview)
        self.assertEqual(before,placement.fingerprint(self.board,api))

    def test_interior_courtyard_edit_invalidates_preview(self):
        shapes=self.courtyard(api.F_CrtYd,8)
        preview=placement.plan(self.board,api)
        shapes[0].SetEnd(self.v(21,16))
        with self.assertRaisesRegex(ValueError,'Board changed'):placement.apply(self.board,api,preview)


try:
    import wx
except ImportError:
    wx=None

@unittest.skipIf(api is None or wx is None,'Native KiCad wx required')
class PreviewGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def test_native_glyphs_stay_inside_reviewed_box_at_every_zoom_and_side(self):
        from silkscreen_label_plugin.ui import LabelPreview
        parent=wx.Frame(None)
        case=fixture.PlacementTests();case.setUp();panel=LabelPreview(parent,case.board)
        try:
            for bottom in (False,True):
                if bottom:
                    case.fp.SetLayer(api.B_Cu);case.text.SetLayer(api.B_SilkS)
                panel.back=bottom;panel.preview=placement.plan(case.board,api)
                self.assertTrue(panel.preview.changes)
                for zoom in (.2,1.,5.,20.):
                    panel.zoom=zoom;bitmap=wx.Bitmap(900,600);dc=wx.MemoryDC(bitmap)
                    panel.draw(dc,(900,600))
                    dc.SelectObject(wx.NullBitmap)
                    boardbox=case.board.GetBoardEdgesBoundingBox()
                    scale=min(840/boardbox.GetWidth(),540/boardbox.GetHeight())*zoom
                    cx=(boardbox.GetLeft()+boardbox.GetRight())/2;cy=(boardbox.GetTop()+boardbox.GetBottom())/2
                    allowed=[]
                    for change in panel.preview.changes:
                        box=change.box;xs=[450+(-1 if bottom else 1)*(x-cx)*scale for x in (box.GetLeft(),box.GetRight())]
                        ys=[300+(y-cy)*scale for y in (box.GetTop(),box.GetBottom())]
                        allowed.append((min(xs)-1,min(ys)-1,max(xs)+1,max(ys)+1))
                    for shapes in panel._glyphs.values():
                        for outer,holes in shapes:
                            for ring in [outer,*holes]:
                                for vx,vy in ring:
                                    x=round(450+(-1 if bottom else 1)*(vx-cx)*scale)
                                    y=round(300+(vy-cy)*scale)
                                    self.assertTrue(any(a<=x<=c and b<=y<=d for a,b,c,d in allowed))
                    self.assertTrue(panel._glyphs)
        finally:
            parent.Destroy();wx.Yield()

if __name__=='__main__':unittest.main()
