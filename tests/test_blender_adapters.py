"""Saved-result geometry, scalar support and non-fabrication checks."""
import copy
import math
import unittest
from unittest.mock import patch

from wayricad_runtime.blender_adapters import normalize


def pi():
    return {'geometry':{'net':'VCC','source_path':'C:/Private/Example/board.kicad_pcb','source_sha256':'abc'},
            'mesh':{'points_mm':[[0,0,.1],[2,0,.1],[0,2,.1],[2,2,.1]],
                    'triangles':[[0,1,2],[1,3,2]]},
            'result':{'potential_V':[3.3,3.2,3.1,None], 'source_voltage_V':3.3,
                      'cell_J_A_mm2':[[3,4],[0,2]],'cell_power_W':[.01,None]}}


def view():
    return {'board_thickness_mm':1.6,
            'outline':[{'outer_mm':[[0,0],[2,0],[2,1],[0,1]],
                        'holes_mm':[[[.5,.2],[.8,.2],[.8,.5],[.5,.5]]]}],
            'drills':[{'contour_mm':[[1,.1],[1.2,.1],[1.1,.3]]}],
            'components':[{'reference':'U1','side':'top','bbox_mm':[.1,.1,.4,.4]}]}


def thermal():
    return {'quick_therm':{'components':[{'reference':'U1','junction_temperature_c':45.}]},
            'board_thermal_view':view(),
            'thermal_network':{
                'layers':[{'name':'F.Cu','z_mm':.1,'x_edges_mm':[0,1,2],
                           'y_edges_mm':[0,1],'values_c':[[30.,40.]]}],
                'components':[{'reference':'U1','junction_c':45.}],
                'transient':{'spatial_index':{'cells':[[1,0],[0,0]],'active_cells_per_layer':2},
                             'frames':[{'time_s':0.,'temperatures_c':[20.,20.,21.]},
                                       {'time_s':1.,'temperatures_c':[41.,31.,48.]}],
                             'components':[{'reference':'U1','storage_node':2,'temperature_kind':'junction'}]}}}


def si():
    return {'schema':'wayricad.quick-si/v1','status':'APPROXIMATE',
            'path':{'net_name':'DATA','segments':[
                {'kind':'track','geometry':'straight','layer':'F.Cu','start_mm':[0,0],
                 'end_mm':[2,0],'width_mm':.2,'impedance_ohm':None,'screening_delay_ns':.01,'resistance_ohm':.1},
                {'kind':'via','geometry':'barrel','layer':'F.Cu','start_mm':[2,0],'end_mm':[2,0]}]}}


class BlenderAdapterTests(unittest.TestCase):
    def test_pi_potential_support_and_source_privacy(self):
        source = pi();saved = copy.deepcopy(source)
        scene = normalize(source)
        self.assertEqual(source,saved)
        obj = scene['objects'][0]
        self.assertEqual(obj['faces'],source['mesh']['triangles'])
        self.assertAlmostEqual(obj['field']['values'][0],3.2)
        self.assertIsNone(obj['field']['values'][1])
        self.assertEqual(obj['vertices_mm'][0],[0.,0.,-.1])
        self.assertEqual(scene['source'],{'board_name':'board.kicad_pcb','sha256':'abc'})
        self.assertNotIn('Private',str(scene))

    def test_pi_units_and_vector_magnitude(self):
        self.assertAlmostEqual(normalize(pi(),metric='drop')['objects'][0]['field']['values'][0],.1)
        field = normalize(pi(),metric='density')['objects'][0]['field']
        self.assertEqual(field['values'],[5.,2.])
        self.assertEqual(field['unit'],'A/mm²')
        self.assertEqual(normalize(pi(),metric='loss')['objects'][0]['field']['values'],[.01,None])

    def test_physical_return_drop_sign(self):
        data = pi();data['result']['physical_return']=True
        self.assertAlmostEqual(normalize(data,metric='drop')['objects'][0]['field']['values'][0],-.1)

    def test_volume_exports_actual_boundary_faces(self):
        data = pi();data['mesh']={'points_mm':[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],'tetrahedra':[[0,1,2,3]]}
        data['result']['potential_V']=[1.,.9,.8,.7]
        data['result']['cell_J_A_mm2']=[[3.,4.,0.]]
        data['result']['cell_power_W']=[.01]
        scene = normalize(data,metric='density')
        self.assertEqual(len(scene['objects'][0]['faces']),4)
        self.assertEqual(scene['objects'][0]['field']['values'],[5.]*4)
        self.assertTrue(any('boundary faces' in text for text in scene['notes']))

    def test_internal_tetrahedron_face_removed(self):
        data = pi();data['mesh']={'points_mm':[[0,0,0],[1,0,0],[0,1,0],[0,0,1],[0,0,-1]],
                                 'tetrahedra':[[0,1,2,3],[0,2,1,4]]}
        data['result']['potential_V']=[1.]*5
        self.assertEqual(len(normalize(data)['objects'][0]['faces']),6)

    def test_bad_potential_and_connectivity_rejected(self):
        data = pi();data['result']['potential_V']=[1.]
        with self.assertRaisesRegex(ValueError,'complete nodal'):normalize(data)
        data = pi();data['mesh']['triangles'][0]=[0,1,100]
        with self.assertRaisesRegex(ValueError,'connectivity'):normalize(data)
        data = pi();data['result']['potential_V'][0]=math.inf
        with self.assertRaisesRegex(ValueError,'finite'):normalize(data)

    def test_thermal_exact_cells_and_frame_mapping(self):
        scene = normalize(thermal())
        obj = scene['objects'][0]
        self.assertEqual(len(obj['faces']),2)
        self.assertEqual(obj['field']['values'],[30.,40.])
        self.assertEqual(obj['field']['frames'][1],{'time_s':1.,'values':[31.,41.]})
        part = next(o for o in scene['objects'] if o['name']=='U1')
        self.assertEqual(part['field']['frames'][1]['values'],[48.]*6)
        self.assertTrue(any('illustrative 0.5' in note for note in scene['notes']))

    def test_board_context_preserves_hole_contours_without_filling_bbox(self):
        scene = normalize(thermal())
        walls = next(o for o in scene['objects'] if o['name'].startswith('Saved board'))
        self.assertEqual(len(walls['faces']),11)
        for face in walls['faces']:
            self.assertEqual({walls['vertices_mm'][i][2] for i in face},{0.,-1.6})

    def test_thermal_unknown_cell_omitted(self):
        data = thermal();data['thermal_network']['layers'][0]['values_c'][0][0]=None
        obj = normalize(data)['objects'][0]
        self.assertEqual(len(obj['faces']),1)
        self.assertEqual(obj['field']['frames'][1]['values'],[41.])

    def test_thermal_missing_spatial_metadata_not_guessed(self):
        data = thermal();del data['thermal_network']['transient']['spatial_index']
        with self.assertRaisesRegex(ValueError,'spatial node mapping'):normalize(data)
        data = thermal();del data['thermal_network']['layers'][0]['x_edges_mm']
        with self.assertRaisesRegex(ValueError,'explicit saved cell edges'):normalize(data)

    def test_si_null_impedance_not_replaced_with_ideal_value(self):
        data = si();data['path']['segments'][0]['screening_z0_ohm']=50.
        scene = normalize(data,metric='impedance')
        self.assertEqual(scene['objects'][0]['field']['values'],[None])
        self.assertEqual(len(scene['objects'][0]['faces']),1)
        self.assertTrue(any('via' in note for note in scene['notes']))
        self.assertTrue(any('coplanar' in note for note in scene['notes']))

    def test_si_layer_height_only_when_supplied(self):
        data = si();data['blender_layer_z_mm']={'F.Cu':-.2}
        scene = normalize(data)
        self.assertEqual({p[2] for p in scene['objects'][0]['vertices_mm']},{-.2})
        self.assertEqual(scene['objects'][0]['field']['values'],[.01])

    def test_trace_only_transient_keeps_samples_and_discontinuities(self):
        data = {'transient':{'times_s':[0.,1.,1.,2.],
                              'loads':[{'id':'U1','voltage_V':[3.3,3.2,3.1,3.15]}],
                              'source_current_A':[.1,.1,1.,1.]}}
        scene = normalize(data)
        self.assertEqual(scene['traces'][0]['time_s'],[0.,1.,1.,2.])
        self.assertFalse(scene['objects'])
        self.assertEqual(scene['tool'],'pi')

    def test_explicit_rc_direct_result_detected(self):
        scene = normalize({'times_s':[0.,1.],'components':[{'reference':'U1','temperature_c':[20.,21.]}]})
        self.assertEqual(scene['tool'],'therm')
        self.assertEqual(scene['traces'][0]['values'],[20.,21.])

    def test_external_batch_case_rejected(self):
        with self.assertRaisesRegex(ValueError,'complete solved case'):
            normalize({'batch':{'cases':[{'name':'External','electrical':{'schema':'reference'}}]}})

    def test_embedded_batch_keeps_case_names(self):
        scene = normalize({'batch':{'cases':[{'name':'Rail A','electrical':pi()}]}})
        self.assertTrue(scene['objects'][0]['name'].startswith('Rail A'))

    def test_mesh_budget_is_not_silent_sampling(self):
        with patch('wayricad_runtime.blender_adapters.MAX_FACES',1):
            with self.assertRaisesRegex(ValueError,'budget'):normalize(pi())

    def test_empty_or_failed_cases_do_not_export_board_as_simulation(self):
        for data in ({'batch':{'cases':[]}}, {'cases':[{'id':'bad','error':'No route'}]},
                     {'transient':{'times_s':[1.,0.],'loads':[{'id':'A','voltage_V':[1.,2.]}]}}):
            with self.assertRaises(ValueError):normalize(data)

    def test_density_dimension_and_sparse_frames_rejected(self):
        data = pi();data['result']['cell_J_A_mm2'][0]=[1.,2.,3.]
        with self.assertRaisesRegex(ValueError,'dimension'):normalize(data,metric='density')
        data = thermal();data['thermal_network']['transient']['frames'][1]['temperatures_c']=[]
        with self.assertRaisesRegex(ValueError,'complete temperatures'):normalize(data)

    def test_component_model_keeps_native_z_with_board_shift(self):
        data = thermal();data['board_thermal_view']['component_models']={'components':{
            'U1':{'vertices_mm':[[0.,0.,1.6],[1.,0.,1.6],[0.,1.,2.1]],'triangles':[[0,1,2]]}}}
        part = next(o for o in normalize(data)['objects'] if o['name']=='U1')
        self.assertAlmostEqual(part['vertices_mm'][2][2],.5)
        self.assertEqual(part['properties']['geometry_meaning'],'Saved component mesh')


if __name__ == '__main__':
    unittest.main()
