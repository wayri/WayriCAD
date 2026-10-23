"""Exact display scope and combined-layer projection preserve solver evidence."""
import copy
import unittest
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import TriMesh
from quick_pi_plugin.report import draw_view, interactive_fields
from quick_pi_plugin.tests.test_report import bundle
from wayricad_runtime.board_render import DisplayScene, visible_primitives, draw_matplotlib


class ViewScopeTests(unittest.TestCase):
    def scene(self):
        row=dict(kind='polygon',role='track',layer=0,uuid='rail',net='Analytical strip',
                 points=[[0,0],[10,0],[10,1],[0,1]],holes=[])
        return DisplayScene(primitives=[row,dict(row,uuid='other',net='GND',
                            points=[[20,0],[30,0],[30,1],[20,1]])],layers={0:'F.Cu'})

    def test_filter_uses_exact_net_identity_and_retains_outline(self):
        scene=self.scene()
        scene['primitives'].append(dict(scene['primitives'][0],role='outline',net='',uuid='edge'))
        self.assertEqual([r['uuid'] for r in visible_primitives(scene,[0],['Analytical strip'])],['rail','edge'])
        self.assertEqual([r['uuid'] for r in visible_primitives(scene,[0],['Analytical'])],['edge'])

    def test_display_paths_reused_and_explicit_invalidation_rebuilds(self):
        scene=self.scene();before=copy.deepcopy(dict(scene));figure=Figure();axes=figure.add_subplot()
        first=draw_matplotlib(axes,scene,highlight_nets=['Analytical strip'])
        second=draw_matplotlib(axes,scene,highlight_nets=['GND'])
        self.assertIs(first[0].get_path(),second[0].get_path())
        self.assertEqual(dict(scene),before)
        scene.invalidate()
        third=draw_matplotlib(axes,scene)
        self.assertIsNot(first[0].get_path(),third[0].get_path())

    def test_default_isolated_view_and_optional_board_context(self):
        data=bundle();data['board_scene']=self.scene()
        figure=Figure();axes=draw_view(figure,data,view='Net')
        self.assertLess(axes.dataLim.xmax,15)
        data['view_settings']={'isolate_nets':False}
        axes=draw_view(figure,data,view='Net')
        self.assertGreater(axes.dataLim.xmax,29)

    def test_plural_source_pads_keep_roles_without_repeated_viewport_captions(self):
        data=bundle();data['request']['source_terminals']=[data['request'].pop('source_terminal')]
        axes=draw_view(Figure(),data,view='Net',board_view=True)
        labels=[artist.get_text() for artist in axes.texts]
        self.assertNotIn('Source',labels);self.assertNotIn('Sink',labels)
        self.assertEqual(sum(artist.get_color()=='#13854c' for artist in axes.lines),1)
        self.assertEqual(sum(artist.get_color()=='#b94535' for artist in axes.lines),1)
        report=draw_view(Figure(),data,view='Net')
        captions=[artist.get_text() for artist in report.texts]
        self.assertEqual(sum(label.startswith('Source:') for label in captions),1)
        self.assertEqual(sum(label.startswith('Sink:') for label in captions),1)

    def test_combined_projection_renders_each_layer_without_averaging(self):
        data=bundle();layers=data['geometry']['layers']
        layers.append(dict(layers[0],id=2,name='B.Cu'))
        count=len(data['mesh']['triangle_layer'])
        data['mesh']['triangle_layer'][count//2:]=[2]*(count-count//2)
        before=copy.deepcopy(data)
        figure=Figure();canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,data,layer='all');canvas.draw()
        image=next(item for item in axes.collections if isinstance(item,TriMesh))
        self.assertEqual(len(image._triangulation.triangles),count)
        self.assertIn('not summed',axes.get_title(loc='left'))
        self.assertEqual(data,before)
        html=interactive_fields(data,'all')
        self.assertIn('Layer 0',html);self.assertIn('Layer 2',html)


if __name__=='__main__':unittest.main()
