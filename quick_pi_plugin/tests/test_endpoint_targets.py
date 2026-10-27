"""Endpoint proximity uses displayed pixels and never guesses between units."""
import unittest

from quick_pi_plugin.endpoint_targets import pick_endpoint, marker_style, pad_center,project_anchors


def anchor(x, y, index=0, *, width=2., height=2., role='sink'):
    outline = [(x-width/2, y-height/2), (x+width/2, y-height/2),
               (x+width/2, y+height/2), (x-width/2, y+height/2)]
    return dict(role=role, index=index, label=f'{role} {index}', center=(x,y), outline=outline)


class EndpointTargetTests(unittest.TestCase):
    def test_proximity_reaches_marker_and_wide_pad_edge(self):
        self.assertEqual(pick_endpoint((12,0), [anchor(0,0)], lambda p:p).index, 0)
        self.assertEqual(pick_endpoint((59,0), [anchor(0,0,width=100)], lambda p:p).index, 0)
        self.assertIsNone(pick_endpoint((66,0), [anchor(0,0,width=100)], lambda p:p))

    def test_direct_pad_hit_wins_over_nearby_sink(self):
        hit=pick_endpoint((0,0), [anchor(0,0,index=1),anchor(3,0,index=0)], lambda p:p)
        self.assertEqual(hit.index,1)
        self.assertFalse(hit.ambiguous)

    def test_midpoint_is_ambiguous_instead_of_list_order(self):
        anchors=[anchor(-4,0,index=1),anchor(4,0,index=0)]
        for rows in (anchors,list(reversed(anchors))):
            hit=pick_endpoint((0,0),rows,lambda p:p)
            self.assertTrue(hit.ambiguous)
        self.assertEqual(pick_endpoint((-2,0),anchors,lambda p:p).index,1)

    def test_projected_overlapping_units_are_ambiguous_even_at_one_center(self):
        self.assertTrue(pick_endpoint((0,0),[anchor(0,0,index=0),anchor(.5,0,index=1)],lambda p:p).ambiguous)

    def test_grouped_pads_and_duplicate_layers_are_one_target(self):
        hit=pick_endpoint((0,0),[anchor(-1,0,index=2),anchor(1,0,index=2),anchor(1,0,index=2)],lambda p:p)
        self.assertEqual(hit.index,2)
        self.assertFalse(hit.ambiguous)

    def test_zoom_does_not_expand_proximity_in_board_units(self):
        rows=[anchor(0,0,width=.1,height=.1)]
        self.assertIsNotNone(pick_endpoint((1,0),rows,lambda p:(p[0]*10,p[1]*10)))
        self.assertIsNone(pick_endpoint((1,0),rows,lambda p:(p[0]*30,p[1]*30)))

    def test_source_target_and_source_sink_tie(self):
        source=anchor(0,0,index=None,role='source')
        self.assertEqual(pick_endpoint((0,0),[source],lambda p:p).role,'source')
        self.assertTrue(pick_endpoint((0,0),[source,anchor(0,0)],lambda p:p).ambiguous)

    def test_cached_bulk_projection_retains_target_and_rejects_far_bounds(self):
        calls=[]
        def transform(points):
            calls.append(len(points))
            return [(x*10,y*10) for x,y in points]
        projected=project_anchors([anchor(0,0),anchor(100,100,index=1)],transform)
        self.assertEqual(calls,[10])
        self.assertEqual(pick_endpoint((20,0),projected,None).index,0)
        self.assertIsNone(pick_endpoint((500,500),projected,None))

    def test_markers_remain_modest_and_translucent(self):
        for is_source in (False,True):
            style=marker_style(is_source)
            self.assertGreater(style['markersize'],4.5)
            self.assertLessEqual(style['markersize'],9.)
            self.assertGreater(style['markerfacecolor'][3],0.)
            self.assertLess(style['markerfacecolor'][3],.5)
        self.assertEqual(pad_center([(0,0),(10,0),(10,2),(0,2),(0,0)]),(5,1))


if __name__=='__main__':unittest.main()
