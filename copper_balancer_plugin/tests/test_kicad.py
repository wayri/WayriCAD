"""Run with KiCad's bundled Python, or skip when pcbnew is unavailable."""
import tempfile
import uuid
import unittest
from unittest.mock import patch
from pathlib import Path
from dataclasses import replace
try:
    import pcbnew as p
except ImportError:
    p = None


@unittest.skipIf(p is None,"Requires KiCad's pcbnew module")
class KiCadTests(unittest.TestCase):
    def test_scoped_geometry_matches_full_board_clearance_and_density(self):
        # The obstacle centre is outside the region; its local clearance reaches
        # inside. A drill larger than its copper pad exercises the hole broad phase.
        fp = p.FOOTPRINT(self.board)
        self.board.Add(fp)
        pad = p.PAD(fp)
        pad.SetAttribute(p.PAD_ATTRIB_SMD)
        layers = p.LSET()
        layers.AddLayer(p.F_Cu)
        pad.SetLayerSet(layers)
        pad.SetSize(p.VECTOR2I(p.FromMM(1),p.FromMM(1)))
        pad.SetPosition(p.VECTOR2I(p.FromMM(36),p.FromMM(20)))
        pad.SetLocalClearance(p.FromMM(3))
        fp.Add(pad)
        hole = p.PAD(fp)
        hole.SetAttribute(p.PAD_ATTRIB_NPTH)
        hole.SetSize(p.VECTOR2I(p.FromMM(1),p.FromMM(1)))
        hole.SetDrillShape(p.PAD_DRILL_SHAPE_OBLONG)
        hole.SetDrillSize(p.VECTOR2I(p.FromMM(8),p.FromMM(2)))
        hole.SetPosition(p.VECTOR2I(p.FromMM(36),p.FromMM(24)))
        fp.Add(hole)
        region = (29,17,34,27)
        full = self.b.Geometry(self.board,p.F_Cu,self.settings)
        scoped = self.b.Geometry(self.board,p.F_Cu,replace(self.settings,region=region))
        for x in (29.2,30,31,32,33,33.5):
            for y in (17.2,19,20,22,23,24,25,26):
                shape = ((x,y),(x+.2,y),(x+.2,y+.2),(x,y+.2))
                self.assertEqual(scoped.accepts(shape),full.accepts(shape),(x,y))
        for bounds in ((29,17,31,20),(31,20,34,24),(29,24,34,27)):
            for a,b in zip(scoped.measure(bounds),full.measure(bounds)):
                self.assertAlmostEqual(a,b,places=5)
        self.assertFalse(scoped.accepts(((33.5,20),(33.7,20),(33.7,20.2),(33.5,20.2))))
        self.assertFalse(scoped.accepts(((33,24),(33.2,24),(33.2,24.2),(33,24.2))))

    def test_scoped_preview_skips_far_track_polygon_conversion(self):
        track = p.PCB_TRACK(self.board)
        track.SetStart(p.VECTOR2I(p.FromMM(60),p.FromMM(40)))
        track.SetEnd(p.VECTOR2I(p.FromMM(62),p.FromMM(41)))
        track.SetLayer(p.F_Cu)
        track.SetWidth(p.FromMM(.25))
        self.board.Add(track)
        distant_id = self.b.item_id(track)
        original = p.PCB_TRACK.TransformShapeToPolygon
        converted = []
        def transform(item,*args):
            converted.append(self.b.item_id(item))
            return original(item,*args)
        with patch.object(p.PCB_TRACK,'TransformShapeToPolygon',transform):
            self.b.Geometry(self.board,p.F_Cu,replace(self.settings,region=(28,18,34,24)))
        self.assertNotIn(distant_id,converted)

    def test_review_stamp_detects_direct_geometry_change(self):
        before = self.b.review_stamp(self.board)
        track = next(item for item in self.board.GetTracks() if not isinstance(item, p.PCB_VIA))
        track.SetWidth(track.GetWidth() + p.FromMM(.1))
        self.assertNotEqual(before, self.b.review_stamp(self.board))

    def test_legacy_generated_ownership_remains_removable(self):
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],self.settings)
        count = self.b.apply_preview(self.board,previews,self.settings)
        groups = self.b.managed_groups(self.board,[p.F_Cu])
        for group in groups:
            group.SetName(self.b.LEGACY_PREFIX + str(p.F_Cu))
        self.assertEqual(len(self.b.managed_items(self.board,[p.F_Cu])),count)
        self.assertEqual(self.b.remove_generated(self.board,[p.F_Cu]),count)
        self.assertEqual(self.b.managed_groups(self.board,[p.F_Cu]),[])
        self.assertTrue(self.b.is_generated_net('CopperBalancer/L0_F.Cu/' + '1'*32 + '/000001'))

    def setUp(self):
        from tools.make_demo import make_board
        from copper_balancer import kicad_backend as backend
        from copper_balancer.engine import Settings
        self.b = backend
        self.board = make_board()
        self.settings = Settings(size=1.4,gap=.5,max_shapes=500)

    def test_holes_edges_keepouts_copper_and_roundtrip(self):
        geo = self.b.Geometry(self.board,p.F_Cu,self.settings)
        # Whole shape checks, not merely centre-point checks.
        self.assertFalse(geo.accepts(((6,6),(8,6),(8,8),(6,8))))
        self.assertFalse(geo.accepts(((48,16),(49,16),(49,17),(48,17))))
        self.assertFalse(geo.accepts(((10,34),(11,34),(11,35),(10,35))))
        self.assertFalse(geo.accepts(((20,17),(22,17),(22,18),(20,18))))
        self.assertFalse(geo.accepts(((.5,5),(2,5),(2,6),(.5,6))))
        self.assertTrue(geo.accepts(((58,5),(59,5),(59,6),(58,6))))
        previews,warnings = self.b.build_preview(self.board,[p.F_Cu,p.B_Cu],self.settings)
        count = sum(len(pr.plan.shapes) for pr in previews)
        self.assertGreater(count,100)
        for pr in previews:
            kernel = self.b.Geometry(self.board,pr.layer,self.settings)
            self.assertTrue(all(kernel.accepts(poly) for poly in pr.plan.shapes))
        self.assertEqual(self.b.apply_preview(self.board,previews,self.settings),count)
        self.assertEqual(len(self.b.managed_groups(self.board,[p.F_Cu,p.B_Cu])),2)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'roundtrip.kicad_pcb'
            p.SaveBoard(str(path),self.board)
            loaded = p.LoadBoard(str(path))
            groups = self.b.managed_groups(loaded,[p.F_Cu,p.B_Cu])
            self.assertEqual(sum(len(g.GetItems()) for g in groups),count)
            self.assertTrue(all(item.IsSolidFill() and item.GetWidth()==0 for g in groups for item in g.GetItems()))
            items = [item for g in groups for item in g.GetItems()]
            names = {item.GetNetname() for item in items}
            self.assertEqual(len(names),count)
            self.assertTrue(all(self.b.is_generated_net(name) for name in names))
            self.assertTrue(all(item.GetNetCode()>0 for item in items))
            self.assertTrue(all(f"/L{item.GetLayer()}_" in item.GetNetname() for item in items))

    def test_replace_is_idempotent_and_remove_preserves_originals(self):
        original = {self.b.item_id(item) for item in self.board.GetDrawings()}
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],self.settings)
        count = self.b.apply_preview(self.board,previews,self.settings)
        again,_ = self.b.build_preview(self.board,[p.F_Cu],self.settings)
        self.assertEqual(previews[0].plan.shapes,again[0].plan.shapes)
        self.assertEqual(self.b.apply_preview(self.board,again,self.settings),count)
        self.assertEqual(len(self.b.managed_groups(self.board,[p.F_Cu])),1)
        self.assertEqual(self.b.remove_generated(self.board,[p.F_Cu]),count)
        self.assertEqual({self.b.item_id(item) for item in self.board.GetDrawings()},original)

    def test_edge_band_excludes_middle_and_density_budget(self):
        geo = self.b.Geometry(self.board,p.B_Cu,replace(self.settings,mode="Edge band",band_width=3))
        self.assertFalse(geo.accepts(((32,20),(33,20),(33,21),(32,21))))
        self.assertTrue(geo.accepts(((32,2),(33,2),(33,3),(32,3))))
        previews,_ = self.b.build_preview(self.board,[p.B_Cu],replace(self.settings,mode="Local density balance",target=20))
        self.assertTrue(all(t.density<=20+1e-5 for t in previews[0].plan.tiles.values()))

    def test_invalid_outline_fails_closed(self):
        with self.assertRaises(ValueError):
            self.b.Geometry(p.BOARD(),p.F_Cu,self.settings)

    def test_unfilled_zone_and_footprint_keepout_are_reserved(self):
        for footprint_zone in (False,True):
            with self.subTest(footprint_zone=footprint_zone):
                parent = next(iter(self.board.GetFootprints())) if footprint_zone else self.board
                zone = p.ZONE(parent)
                zone.SetLayer(p.B_Cu)
                zone.SetIsRuleArea(footprint_zone)
                outline = zone.Outline()
                outline.NewOutline()
                for x,y in ((30,8),(40,8),(40,14),(30,14)):
                    outline.Append(p.FromMM(x),p.FromMM(y))
                parent.Add(zone)
                geo = self.b.Geometry(self.board,p.B_Cu,self.settings)
                self.assertFalse(geo.accepts(((33,10),(34,10),(34,11),(33,11))))
                if not footprint_zone:
                    self.assertTrue(geo.warnings)

    def test_slotted_hole_protected_on_back_layer(self):
        fp = p.FOOTPRINT(self.board)
        self.board.Add(fp)
        pad = p.PAD(fp)
        pad.SetAttribute(p.PAD_ATTRIB_NPTH)
        pad.SetDrillShape(p.PAD_DRILL_SHAPE_OBLONG)
        pad.SetDrillSize(p.VECTOR2I(p.FromMM(8),p.FromMM(2)))
        pad.SetSize(p.VECTOR2I(p.FromMM(8),p.FromMM(2)))
        pad.SetPosition(p.VECTOR2I(p.FromMM(35),p.FromMM(20)))
        fp.Add(pad)
        geo = self.b.Geometry(self.board,p.B_Cu,self.settings)
        self.assertFalse(geo.accepts(((37,19.8),(38,19.8),(38,20.2),(37,20.2))))

    def test_failed_apply_restores_previous_fill(self):
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],replace(self.settings,max_shapes=10))
        self.b.apply_preview(self.board,previews,self.settings)
        before = {self.b.item_id(item) for item in self.board.GetDrawings()}
        original_add = self.board.Add
        fail = [True]
        def add(item):
            if isinstance(item,p.PCB_SHAPE) and fail[0]:
                fail[0] = False
                raise RuntimeError("injected write failure")
            return original_add(item)
        with patch.object(self.board,'Add',side_effect=add):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                self.b.apply_preview(self.board,previews,self.settings)
        self.assertEqual(before,{self.b.item_id(item) for item in self.board.GetDrawings()})
        groups = self.b.managed_groups(self.board,[p.F_Cu])
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0].GetItems()),10)

    def test_unique_names_skip_collision_and_do_not_reuse_existing_nets(self):
        first = uuid.UUID('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')
        second = uuid.UUID('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')
        name = f'WayriCADCopper/L{p.F_Cu}_F.Cu/{first.hex}/000001'
        original = p.NETINFO_ITEM(self.board,name)
        self.board.Add(original)
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],replace(self.settings,max_shapes=3))
        with patch.object(self.b.uuid,'uuid4',side_effect=[first,second]):
            self.b.apply_preview(self.board,previews,self.settings)
        names = {item.GetNetname() for item in self.b.managed_items(self.board,[p.F_Cu])}
        self.assertEqual(len(names),3)
        self.assertNotIn(name,names)
        self.assertTrue(all(second.hex in n for n in names))
        self.b.remove_generated(self.board,[p.F_Cu])
        self.assertIsNotNone(self.board.FindNet(name))
        self.assertTrue(all(self.board.FindNet(n) is None for n in names))

    def test_remove_by_layer_survives_ungrouping_and_preserves_other_layer(self):
        previews,_ = self.b.build_preview(self.board,[p.F_Cu,p.B_Cu],replace(self.settings,max_shapes=8))
        self.b.apply_preview(self.board,previews,self.settings)
        back = {self.b.item_id(item):item.GetNetname() for item in self.b.managed_items(self.board,[p.B_Cu])}
        front_nets = {item.GetNetname() for item in self.b.managed_items(self.board,[p.F_Cu])}
        group = self.b.managed_groups(self.board,[p.F_Cu])[0]
        for item in list(group.GetItems()):
            group.RemoveItem(item)
        self.board.Remove(group)
        self.assertEqual(self.b.remove_generated(self.board,[p.F_Cu]),8)
        self.assertEqual(self.b.managed_items(self.board,[p.F_Cu]),[])
        self.assertEqual(back,{self.b.item_id(item):item.GetNetname() for item in self.b.managed_items(self.board,[p.B_Cu])})
        self.assertTrue(all(self.board.FindNet(name) is None for name in front_nets))
        self.assertIsNotNone(self.board.FindNet('GND'))

    def test_moved_shape_can_be_removed_on_current_layer(self):
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],replace(self.settings,max_shapes=3))
        self.b.apply_preview(self.board,previews,self.settings)
        items = self.b.managed_items(self.board,[p.F_Cu])
        items[0].SetLayer(p.B_Cu)
        self.assertEqual(self.b.remove_generated(self.board,[p.B_Cu]),1)
        self.assertEqual(len(self.b.managed_items(self.board,[p.F_Cu])),2)
        self.assertEqual(len(self.b.managed_groups(self.board,[p.F_Cu])[0].GetItems()),2)

    def test_used_generated_net_is_retained_for_other_items(self):
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],replace(self.settings,max_shapes=1))
        self.b.apply_preview(self.board,previews,self.settings)
        item = self.b.managed_items(self.board,[p.F_Cu])[0]
        name,code = item.GetNetname(),item.GetNetCode()
        track = next(iter(self.board.GetTracks()))
        track.SetNetCode(code)
        self.b.remove_generated(self.board,[p.F_Cu])
        self.assertIsNotNone(self.board.FindNet(name))
        self.assertEqual(track.GetNetname(),name)

    def test_net_cleanup_failure_rolls_back_nets_shapes_and_groups(self):
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],replace(self.settings,max_shapes=3))
        self.b.apply_preview(self.board,previews,self.settings)
        before_items = {self.b.item_id(item):item.GetNetname() for item in self.b.managed_items(self.board,[p.F_Cu])}
        before_nets = {str(name) for name in self.board.GetNetsByName().keys()}
        original_remove = self.board.Remove
        removed = [0]
        def remove(item):
            if isinstance(item,p.NETINFO_ITEM):
                removed[0] += 1
                if removed[0] == 2:
                    raise RuntimeError('injected net cleanup failure')
            return original_remove(item)
        with patch.object(self.board,'Remove',side_effect=remove):
            with self.assertRaisesRegex(RuntimeError,'injected net'):
                self.b.remove_generated(self.board,[p.F_Cu])
        self.assertEqual(before_nets,{str(name) for name in self.board.GetNetsByName().keys()})
        self.assertEqual(before_items,{self.b.item_id(item):item.GetNetname() for item in self.b.managed_items(self.board,[p.F_Cu])})
        self.assertEqual(len(self.b.managed_groups(self.board,[p.F_Cu])[0].GetItems()),3)

    def test_replace_one_layer_preserves_other_layer_nets(self):
        settings = replace(self.settings,max_shapes=5)
        previews,_ = self.b.build_preview(self.board,[p.F_Cu,p.B_Cu],settings)
        self.b.apply_preview(self.board,previews,settings)
        back = {item.GetNetname() for item in self.b.managed_items(self.board,[p.B_Cu])}
        old_front = {item.GetNetname() for item in self.b.managed_items(self.board,[p.F_Cu])}
        previews,_ = self.b.build_preview(self.board,[p.F_Cu],settings)
        self.b.apply_preview(self.board,previews,settings)
        front = {item.GetNetname() for item in self.b.managed_items(self.board,[p.F_Cu])}
        self.assertTrue(front.isdisjoint(old_front))
        self.assertTrue(all(self.board.FindNet(name) is None for name in old_front))
        self.assertEqual(back,{item.GetNetname() for item in self.b.managed_items(self.board,[p.B_Cu])})


if __name__ == '__main__':
    unittest.main()
