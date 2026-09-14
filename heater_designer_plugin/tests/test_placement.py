"""Generated conductors must not short existing copper or bypass winding paths."""
import unittest
try:
    import pcbnew as p
except ImportError:
    p=None


@unittest.skipIf(p is None,'Requires native KiCad Python')
class PlacementTests(unittest.TestCase):
    def checks(self):
        from heater_designer_plugin.placement import validate_placement as heater
        from planar_magnetics_plugin.placement import validate_placement as magnetics
        return heater,magnetics

    def track(self,board,x0,y0,x1,y1,layer=None):
        item=p.PCB_TRACK(board)
        item.SetStart(p.VECTOR2I(p.FromMM(x0),p.FromMM(y0)))
        item.SetEnd(p.VECTOR2I(p.FromMM(x1),p.FromMM(y1)))
        item.SetWidth(p.FromMM(.3));item.SetLayer(p.F_Cu if layer is None else layer)
        return item

    def test_same_net_copper_cannot_short_around_generated_conductor(self):
        board=p.BOARD();net=p.NETINFO_ITEM(board,'HEATER');board.Add(net)
        existing=self.track(board,0,2,8,2);existing.SetNet(net);board.Add(existing)
        proposed=self.track(board,4,0,4,5);proposed.SetNet(net)
        for check in self.checks():
            with self.assertRaisesRegex(ValueError,'existing geometry'):
                check(board,[proposed],p)
        self.assertEqual(len(list(board.GetTracks())),1)

    def test_clear_location_and_other_layer_remain_available(self):
        board=p.BOARD();existing=self.track(board,0,2,8,2);board.Add(existing)
        for proposed in (self.track(board,12,1,12,5),self.track(board,4,0,4,5,p.B_Cu)):
            for check in self.checks():check(board,[proposed],p)
        self.assertEqual(len(list(board.GetTracks())),1)

    def test_zone_boundary_and_via_span_are_reserved(self):
        board=p.BOARD();zone=p.ZONE(board);zone.SetLayer(p.B_Cu);zone.SetIsRuleArea(True)
        outline=zone.Outline();outline.NewOutline()
        for x,y in ((1,1),(5,1),(5,5),(1,5)):outline.Append(p.FromMM(x),p.FromMM(y))
        board.Add(zone)
        via=p.PCB_VIA(board);via.SetPosition(p.VECTOR2I(p.FromMM(3),p.FromMM(3)))
        via.SetWidth(p.FromMM(.6));via.SetDrill(p.FromMM(.3));via.SetViaType(p.VIATYPE_THROUGH)
        via.SetLayerPair(p.F_Cu,p.B_Cu)
        for check in self.checks():
            with self.assertRaisesRegex(ValueError,'B.Cu'):check(board,[via],p)


if __name__=='__main__':unittest.main()
