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

    def test_selected_nets_filter_saved_copper_and_cells_in_lockstep(self):
        import numpy as np
        data=bundle();data['board_scene']=self.scene()
        data['geometry']['nets']=['Analytical strip','GND']
        mesh=data['mesh'];count=len(mesh['triangles']);split=count//2
        mesh['display_net_domains']=[dict(net='Analytical strip',first_cell=0,end_cell=split),
                                      dict(net='GND',first_cell=split,end_cell=count)]
        figure=Figure()
        axes=draw_view(figure,data,board_view=True,net_scope='Selected nets',visible_nets=['Analytical strip'],
                       color_limits=(0,1),show_context=False)
        self.assertLess(axes.dataLim.xmax,15)
        self.assertEqual(axes._wayricad_color_scale['limits'],(0,1))
        image=next(item for item in axes.collections if isinstance(item,TriMesh))
        self.assertEqual(len(image._triangulation.triangles),split)
        self.assertTrue(np.isfinite(image.get_array()).any())
        axes=draw_view(figure,data,board_view=True,net_scope='Selected nets',visible_nets=['Analytical strip'],
                       dim_context=True,show_context=False)
        self.assertGreater(axes.dataLim.xmax,29)
        self.assertTrue(any((patch.get_alpha() or 1)<.16 for patch in axes.patches))
        axes=draw_view(figure,data,board_view=True,net_scope='Selected nets',
                       visible_nets=['Analytical strip','GND'],show_context=False)
        self.assertGreater(axes.dataLim.xmax,29)

    def test_silk_side_is_independent_of_copper_layer_and_outline(self):
        data=bundle();scene=self.scene()
        scene['layers'].update({37:'F.SilkS',36:'B.SilkS'})
        row=scene['primitives'][0]
        scene['primitives'].extend(
            dict(row, role='reference', layer=layer, uuid=identifier)
            for layer,identifier in [(37,'front'),(36,'back')])
        data['board_scene']=scene
        axes=draw_view(Figure(),data,board_view=True,layer=0,net_scope='Full board',
                       show_context=False,show_copper=False,silk_sides=('B.',))
        gids=[patch.get_gid() for patch in axes.patches]
        self.assertIn('board-context:reference:back',gids)
        self.assertNotIn('board-context:reference:front',gids)

    def test_legacy_series_without_verified_domain_omits_partial_overlay(self):
        data=bundle();data['board_scene']=self.scene()
        data['geometry']['nets']=['Analytical strip','GND']
        axes=draw_view(Figure(),data,board_view=True,net_scope='Selected nets',
                       visible_nets=['Analytical strip'],show_context=False)
        self.assertIsNone(axes._wayricad_color_scale)
        self.assertTrue(any('per-net field identities' in label.get_text() for label in axes.texts))

    def test_unavailable_cells_and_solved_zero_have_different_artists(self):
        data=bundle();data['board_scene']=self.scene()
        values=data['result']['cell_J_A_mm2']
        values[0]=None;values[1]=[0.0,0.0]
        axes=draw_view(Figure(),data,board_view=True,net_scope='Analyzed nets',
                       metric='density',field_style='cells',show_context=False)
        self.assertEqual(sum(artist.get_gid()=='pi-unsolved-field' for artist in axes.collections),1)
        self.assertIn(0,axes._wayricad_color_mappable.get_array())

    def test_pin_and_representative_route_follow_view_scope(self):
        data=bundle();data['board_scene']=self.scene()
        pins=[dict(layer=0,net='Analytical strip',point=(1.2,.3))]
        figure=Figure()
        axes=draw_view(figure,data,board_view=True,net_scope='Full board',route_ids=('rail',),pins=pins)
        self.assertTrue(any(artist.get_gid()=='pi-representative-route' for artist in axes.patches))
        self.assertTrue(any(text.get_text()=='P1' for text in axes.texts))
        axes=draw_view(figure,data,board_view=True,net_scope='Selected nets',visible_nets=['GND'],
                       route_ids=('rail',),pins=pins)
        self.assertFalse(any(artist.get_gid()=='pi-representative-route' for artist in axes.patches))
        self.assertFalse(any(text.get_text()=='P1' for text in axes.texts))
        axes=draw_view(figure,data,board_view=True,net_scope='Analyzed nets',pins=pins)
        self.assertTrue(any(text.get_text()=='P1' for text in axes.texts))

    def test_hover_reports_exact_cell_net_layer_and_units(self):
        from matplotlib.backend_bases import MouseEvent
        import numpy as np
        from quick_pi_plugin.viewport_probe import attach_viewport_probes

        data=bundle()
        figure=Figure();canvas=FigureCanvasAgg(figure)
        axes=draw_view(figure,data,board_view=True,net_scope='Analyzed nets',metric='density')
        controller=attach_viewport_probes(canvas,axes,data,0,'density',None,lambda:data['result'])
        canvas.draw()
        mesh=data['mesh'];verts=np.asarray(mesh['points_mm'])[mesh['triangles'][0],:2]
        point=axes.transData.transform(verts.mean(axis=0))
        event=MouseEvent('motion_notify_event',canvas,*point)
        canvas.callbacks.process('motion_notify_event',event)
        visible=[text.get_text() for text in axes.texts if text.get_visible()]
        self.assertTrue(any('Analytical strip · F.Cu' in text and 'A/mm²' in text
                            and 'X ' in text and 'Y ' in text for text in visible))
        controller['disconnect']()

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
