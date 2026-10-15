"""Indexed picking and batched drawing must retain display geometry semantics."""
import json
import unittest
from unittest.mock import patch

from wayricad_runtime import board_render as render


def scene(count=1000):
    rows = []
    for i in range(count):
        x, y = (i % 100)*2., (i // 100)*2.
        rows.append(dict(kind='polygon', role='track', layer=0, uuid=str(i), net='N'+str(i % 3),
                         points=[[x,y],[x+1,y],[x+1,y+1],[x,y+1]], holes=[]))
    return render.prepare_scene(dict(primitives=rows))


class IndexedPickingTests(unittest.TestCase):
    def test_matches_linear_for_layers_nets_edges_holes_and_drills(self):
        data = scene()
        data['primitives'] += [dict(kind='polygon', role='zone', layer=31, uuid='z', net='GND',
                                  points=[[0,0],[200,0],[200,20],[0,20]],
                                  holes=[[[3,3],[5,3],[5,5],[3,5]]]),
                               dict(kind='polygon', role='drill', layer=0, uuid='0', net='',
                                  points=[[.2,.2],[.8,.2],[.8,.8],[.2,.8]])]
        for x, y in ((.5,.5),(1,1),(.1,.1),(4,4),(90,10),(200,20),(-1,0)):
            for layers in (None,[0],[31]):
                for net in (None,'GND','N0'):
                    self.assertEqual(render.hit_test(data,x,y,layers,net),
                                     render.hit_test(dict(data),x,y,layers,net))
        self.assertEqual(json.loads(json.dumps(data)),dict(data))

    def test_index_reduces_geometry_work_and_can_be_invalidated(self):
        data = scene(40000)
        with patch.object(render, '_inside', wraps=render._inside) as inside:
            self.assertEqual(len(render.hit_test(data,.1,.1)),1)
            self.assertLess(inside.call_count,20)
        data['primitives'][0]['points'] = [[-10,-10],[-9,-10],[-9,-9],[-10,-9]]
        data.invalidate()
        self.assertEqual(render.hit_test(data,.1,.1),[])
        self.assertEqual(len(render.hit_test(data,-9.5,-9.5)),1)

    def test_collection_keeps_holes_highlights_and_data_bounds(self):
        try:
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.figure import Figure
        except ImportError:
            self.skipTest('Matplotlib required')
        data = scene()
        data['primitives'][0]['holes'] = [[[.3,.3],[.7,.3],[.7,.7],[.3,.7]]]
        figure = Figure();FigureCanvasAgg(figure);axes = figure.add_subplot()
        artists = render.draw_matplotlib(axes,data,highlight_ids=['1'])
        self.assertLess(len(artists),10)
        self.assertEqual(sum(len(item.get_paths()) for item in artists),1000)
        self.assertEqual(len(axes.patches),0)
        first = next(path for item in artists for path in item.get_paths() if len(path.vertices)==10)
        self.assertEqual(sum(first.codes==1),2)  # outer and hole remain separate rings
        self.assertTrue(any(item.get_zorder()==6 for item in artists))
        axes.autoscale_view();figure.canvas.draw()
        self.assertLessEqual(axes.dataLim.x0,0);self.assertGreaterEqual(axes.dataLim.x1,199)


if __name__ == '__main__':
    unittest.main()
