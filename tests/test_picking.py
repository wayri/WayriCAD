"""Geometry hit tests used by board input selection and 3D cursor probes."""
import unittest
from wayricad_runtime.picking import segment_distance,triangle_hit,ray_box,pick_meshes

class PickingTests(unittest.TestCase):
    def test_segment_endpoints_and_degenerate_point(self):
        self.assertEqual(segment_distance((2,1),(0,0),(1,0)),2**.5)
        self.assertEqual(segment_distance((1,.5),(0,0),(2,0)),.5)
        self.assertEqual(segment_distance((3,4),(0,0),(0,0)),5)
    def test_front_ray_exact_triangle_and_parallel_rejection(self):
        triangle=[(0,0,0),(2,0,0),(0,2,0)]
        self.assertEqual(triangle_hit((.5,.5,2),(0,0,-1),triangle),2)
        self.assertIsNone(triangle_hit((2,2,2),(0,0,-1),triangle))
        self.assertIsNone(triangle_hit((.5,.5,2),(0,0,1),triangle))
        self.assertIsNone(triangle_hit((.5,.5,2),(1,0,0),triangle))
    def test_box_axes_and_nearest_actual_surface(self):
        self.assertFalse(ray_box((3,0,2),(0,0,-1),[0,0,0,2,2,1]))
        def body(z):return {'ref':str(z),'bounds':[0,0,z,2,2,z],'mesh':{'vertices':[[0,0,z],[2,0,z],[0,2,z]],'faces':[[0,1,2]]}}
        result=pick_meshes((.5,.5,3),(0,0,-1),[body(0),body(1)])
        self.assertEqual(result['reference'],'1')
        self.assertEqual(result['position'],[.5,.5,1])


class ClippedPickingTests(unittest.TestCase):
    def test_clipped_front_face_does_not_hide_visible_back_face(self):
        mesh={'vertices':[[0,0,2],[1,0,2],[0,1,2],[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2],[3,4,5]]}
        body={'ref':'U1','mesh':mesh,'bounds':[0,0,0,1,1,2]}
        ray=((.25,.25,3),(0,0,-1),[body])
        self.assertEqual(pick_meshes(*ray)['position'][2],2)
        hit=pick_meshes(*ray,accept_hit=lambda p:p[2]<1)
        self.assertEqual(hit['position'],[.25,.25,0.])
        self.assertIsNone(pick_meshes(*ray,accept_hit=lambda p:False))
