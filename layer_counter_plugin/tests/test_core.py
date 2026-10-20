"""Native physical-layer mapping, read-only geometry and reversible insertion."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    import pcbnew as api
except ImportError:
    api=None
from layer_counter_plugin import core


def board(count=6):
    b=api.BOARD();b.SetCopperLayerCount(count)
    points=[(0,0),(100,0),(100,80),(0,80)]
    for a,z in zip(points,points[1:]+points[:1]):
        edge=api.PCB_SHAPE(b);edge.SetLayer(api.Edge_Cuts);edge.SetShape(api.SHAPE_T_SEGMENT)
        edge.SetStart(api.VECTOR2I(api.FromMM(a[0]),api.FromMM(a[1])))
        edge.SetEnd(api.VECTOR2I(api.FromMM(z[0]),api.FromMM(z[1])));b.Add(edge)
    return b


@unittest.skipIf(api is None,'Native KiCad bindings required')
class CounterTests(unittest.TestCase):
    def test_all_styles_and_stack_sizes_are_read_only_and_round_trip(self):
        for count in (2,6,32):
            for style in core.STYLES:
                with self.subTest(count=count,style=style):
                    b=board(count);before=core.fingerprint(b,api)
                    review=core.plan(b,api,dict(style=style))
                    self.assertEqual(before,core.fingerprint(b,api))
                    self.assertEqual([r['text'] for r in review.labels],['L'+str(n) for n in range(1,count+1)])
                    self.assertEqual({i.GetLayer() for i in review.items if isinstance(i,api.PCB_TEXT)},set(review.settings['layers']))
                    tx=core.apply(b,api,review)
                    self.assertEqual(len(list(tx.group.GetItems())),len(review.items))
                    applied=core.fingerprint(b,api)
                    tx.undo();self.assertEqual(before,core.fingerprint(b,api))
                    tx.redo();self.assertEqual(applied,core.fingerprint(b,api))

    def test_subset_uses_physical_numbers_not_index_or_native_id(self):
        b=board(6);rows=core.copper_layers(b,api)
        review=core.plan(b,api,dict(layers=[rows[-1][0],rows[1][0]]))
        self.assertEqual([r['text'] for r in review.labels],['L2','L6'])
        self.assertFalse(review.labels[0]['mirror']);self.assertTrue(review.labels[1]['mirror'])
        self.assertEqual(review.labels[1]['layer'],api.B_Cu)

    def test_explicit_core_pairs_mirror_or_overlap(self):
        b=board(6);layers=[row[0] for row in core.copper_layers(b,api)[:4]]
        mirrored=core.plan(b,api,dict(style='core-mirrored',layers=layers,core_pairs='L1/L2,L3/L4'))
        self.assertEqual([r['mirror'] for r in mirrored.labels],[False,True,False,True])
        self.assertAlmostEqual(mirrored.labels[0]['x']+mirrored.labels[1]['x'],20)
        overlapped=core.plan(b,api,dict(style='core-overlap',layers=layers,core_pairs='L1/L2,L3/L4'))
        self.assertEqual(overlapped.labels[0]['x'],overlapped.labels[1]['x'])
        self.assertEqual(overlapped.labels[2]['x'],overlapped.labels[3]['x'])
        self.assertNotEqual(overlapped.labels[0]['x'],overlapped.labels[2]['x'])

    def test_zone_only_keepout_covers_all_native_graphic_bounds(self):
        for style in core.STYLES:
            b=board();review=core.plan(b,api,dict(style=style))
            zone=review.items[-1]
            self.assertIsInstance(zone,api.ZONE);self.assertTrue(zone.GetIsRuleArea())
            self.assertTrue(zone.GetDoNotAllowZoneFills())
            for method in ('GetDoNotAllowTracks','GetDoNotAllowVias','GetDoNotAllowPads','GetDoNotAllowFootprints'):
                self.assertFalse(getattr(zone,method)())
            self.assertEqual(set(zone.GetLayerSet().Seq()),set(review.settings['layers']))
            for item in review.items[:-1]:self.assertTrue(zone.GetBoundingBox().Contains(item.GetBoundingBox()))

    def test_saved_group_reopens_and_moves_keepout_and_copper_together(self):
        b=board();review=core.plan(b,api,dict(style='octagon'));tx=core.apply(b,api,review)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'counter.kicad_pcb';api.SaveBoard(str(path),b)
            reopened=api.LoadBoard(str(path));group=next(iter(reopened.Groups()))
            members=list(group.GetItems());self.assertEqual(len(members),len(review.items))
            previous={str(i.m_Uuid.AsString()):(i.GetPosition().x,i.GetPosition().y) for i in members}
            group.Move(api.VECTOR2I(api.FromMM(5),api.FromMM(7)))
            for item in group.GetItems():
                x,y=previous[str(item.m_Uuid.AsString())]
                self.assertEqual((item.GetPosition().x,item.GetPosition().y),(x+api.FromMM(5),y+api.FromMM(7)))
            zone=next(z for z in reopened.Zones() if z.GetIsRuleArea())
            self.assertTrue(zone.GetDoNotAllowZoneFills())

    def test_stale_source_and_preview_geometry_are_rejected(self):
        b=board();review=core.plan(b,api)
        edge=next(iter(b.GetDrawings()));edge.SetWidth(api.FromMM(.3))
        with self.assertRaisesRegex(ValueError,'Board changed'):core.apply(b,api,review)
        b=board();review=core.plan(b,api);review.items[0].SetText('WRONG')
        with self.assertRaisesRegex(ValueError,'geometry changed'):core.apply(b,api,review)
        self.assertFalse(list(b.Groups()))
        b=board();tx=core.apply(b,api,core.plan(b,api));tx.group.Move(api.VECTOR2I(100,0))
        with self.assertRaisesRegex(ValueError,'Board changed'):tx.undo()

    def test_identical_other_board_cannot_receive_a_source_preview(self):
        a=api.BOARD();b=api.BOARD()
        self.assertEqual(core.fingerprint(a,api),core.fingerprint(b,api))
        preview=core.plan(a,api)
        with self.assertRaisesRegex(ValueError,'another board'):core.apply(b,api,preview)
        self.assertFalse(list(b.Groups()));self.assertFalse(list(b.Zones()))

    def test_post_mutation_add_and_remove_failures_restore_board(self):
        for operation in ('Add','Remove'):
            b=board();review=core.plan(b,api)
            tx=core.Transaction(b,api,review)
            if operation=='Remove':tx.redo()
            before=core.fingerprint(b,api);real=getattr(b,operation);calls=[0]
            def fail(item):
                real(item);calls[0]+=1
                if calls[0]==3:raise RuntimeError('Injected post-mutation failure')
            with patch.object(b,operation,side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'post-mutation'):
                    (tx.redo if operation=='Add' else tx.undo)()
            self.assertEqual(before,core.fingerprint(b,api))

    def test_refilled_copper_zones_exclude_counter_on_every_selected_layer(self):
        b=board(6)
        net=api.NETINFO_ITEM(b,'GND');b.Add(net)
        zones=[]
        for layer,_,_ in core.copper_layers(b,api):
            z=api.ZONE(b);z.SetLayer(layer);z.SetNet(net)
            z.SetLocalClearance(api.FromMM(.25));z.SetMinThickness(api.FromMM(.15))
            z.SetIslandRemovalMode(api.ISLAND_REMOVAL_MODE_NEVER)
            poly=z.Outline();poly.NewOutline()
            for x,y in ((1,1),(99,1),(99,79),(1,79)):poly.Append(api.FromMM(x),api.FromMM(y))
            b.Add(z);zones.append((layer,z))
        review=core.plan(b,api,dict(style='core-overlap'))
        core.apply(b,api,review)
        api.ZONE_FILLER(b).Fill(b.Zones())
        for layer,z in zones:
            filled=z.GetFilledPolysList(layer)
            self.assertTrue(filled.Contains(api.VECTOR2I(api.FromMM(70),api.FromMM(60))))
            left,top,right,bottom=review.bounds
            for x,y in (((left+right)/2,(top+bottom)/2),(left+.05,top+.05),(right-.05,bottom-.05)):
                self.assertFalse(filled.Contains(api.VECTOR2I(api.FromMM(x),api.FromMM(y))))

    def test_invalid_inputs_never_mutate_board(self):
        b=board();before=core.fingerprint(b,api)
        cases=[dict(x=10000),dict(style='circle',size=100),dict(layers=[]),dict(layers=[api.F_SilkS]),dict(layers=[0,0]),dict(size=float('nan')),
               dict(stroke=1),dict(margin=0),dict(style='unknown'),dict(style='core-overlap',core_pairs='L1/L3'),
               dict(style='core-mirrored',core_pairs='L1/L2,L1/L2,L5/L6'),dict(style='core-overlap',core_pairs='L1/L2')]
        for settings in cases:
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):core.plan(b,api,settings)
                self.assertEqual(before,core.fingerprint(b,api))


if __name__=='__main__':unittest.main()
