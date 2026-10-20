"""Automatic sizing changes real FV geometry and preserves numerical contracts."""
import copy
import unittest
from pathlib import Path
import tempfile

from quick_therm_plugin.mesh_sizing import recommend_mesh, refine_edges
from quick_therm_plugin.tests.test_thermal_multilayer import inputs
from quick_therm_plugin.thermal_multilayer import solve_multilayer_thermal, solve_multilayer_thermal_convergence


class AutomaticMeshTests(unittest.TestCase):
    def source_case(self):
        geometry, view, result, settings = inputs()
        view['components'][0]['bbox_mm'] = [5.7, 5.7, 6.3, 6.3]
        settings['mesh_mode'] = 'auto'
        return geometry, view, result, settings

    def test_auto_uses_actual_nonuniform_intervals_and_conserves_heat(self):
        geometry, view, result, settings = self.source_case()
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        edges = solved['layers'][0]['x_edges_mm']
        widths = {round(b-a, 8) for a, b in zip(edges, edges[1:])}
        self.assertGreater(len(widths), 1)
        self.assertLess(abs(solved['heat_balance']['residual_w']), 1e-6)
        sizing = solved['mesh']['automatic_sizing']
        self.assertLess(sizing['minimum_cell_size_mm'], sizing['maximum_cell_size_mm'])
        self.assertGreaterEqual(solved['components'][0]['source_cells'], 4)
        self.assertFalse(sizing['budget_limited'])

    def test_manual_override_keeps_requested_grid_and_existing_refinement(self):
        geometry, view, result, settings = self.source_case()
        settings.update(mesh_mode='manual', grid_cells_long_axis=32)
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertEqual(solved['mesh']['nx'], 32)
        self.assertIsNone(solved['mesh']['automatic_sizing'])
        settings['source_refinement_factor'] = 2
        refined = solve_multilayer_thermal(geometry, view, result, settings)
        self.assertGreater(refined['mesh']['nx'], 32)

    def test_auto_reference_uniform_heating_matches_energy_balance(self):
        geometry, view, result, settings = inputs()
        view['components'][0]['bbox_mm'] = [0, 0, 12, 12]
        settings.update(mesh_mode='auto', board_h_w_m2k=50., board_emissivity=0.)
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        # Uniform heating on the top plane: two isothermal layers, each with
        # hA to ambient, joined by dielectric kA/gap. Not one zero-thickness
        # sheet: retaining the vertical resistance gives different surfaces.
        surface_g = 50.*.012*.012
        vertical_g = .3*.012*.012/.00153
        top_rise = 1./(surface_g+surface_g*vertical_g/(surface_g+vertical_g))
        bottom_rise = top_rise*vertical_g/(surface_g+vertical_g)
        for layer, rise in zip(solved['layers'], (top_rise, bottom_rise)):
            self.assertAlmostEqual(layer['sampled_min_c'], 20.+rise, places=5)
            self.assertAlmostEqual(layer['sampled_max_c'], 20.+rise, places=5)
        self.assertLess(abs(solved['heat_balance']['residual_w']), 1e-7)

    def test_study_uses_requested_distinct_grids_in_auto_mode(self):
        geometry, view, result, settings = self.source_case()
        solved = solve_multilayer_thermal_convergence(geometry, view, result, settings,
            {'grid_cells_long_axis': [24, 32], 'maximum_change_c': 1e6,
             'maximum_field_change_c': 1e6, 'minimum_source_cells': 1})
        acceptance = solved['mesh_acceptance']
        self.assertEqual([row['base_grid'] for row in acceptance['effective_meshes']], [24, 32])
        self.assertTrue(acceptance['distinct_spatial_meshes'])
        self.assertNotEqual(acceptance['effective_meshes'][0]['nx'], acceptance['effective_meshes'][1]['nx'])

    def test_budget_limits_resolution_without_claiming_accuracy(self):
        geometry, view, result, settings = self.source_case()
        settings['auto_mesh_max_layer_cells'] = 1152
        solved = solve_multilayer_thermal(geometry, view, result, settings)
        sizing = solved['mesh']['automatic_sizing']
        self.assertLessEqual(solved['mesh']['nx']*solved['mesh']['ny']*2, 1152)
        self.assertTrue(sizing['budget_limited'])
        self.assertGreater(sizing['unresolved_feature_count'], 0)
        self.assertLess(abs(solved['heat_balance']['residual_w']), 1e-6)
        geometry['layers'] *= 6
        with self.assertRaisesRegex(ValueError, 'minimum base grid'):
            recommend_mesh(geometry, view, result, settings)

    def test_polygon_tessellation_does_not_change_recommendation(self):
        geometry, view, result, settings = self.source_case()
        original = recommend_mesh(geometry, view, result, settings)
        dense = copy.deepcopy(geometry)
        for layer in dense['layers']:
            layer['polygons_mm'][0]['outer'] = [[i*.01, 0] for i in range(1201)] + [[12, 12], [0, 12]]
        changed = recommend_mesh(dense, view, result, settings)
        self.assertEqual(original['recommended_grid_cells_long_axis'], changed['recommended_grid_cells_long_axis'])
        self.assertEqual(original['features'], changed['features'])

    def test_refinement_progress_preserves_cancellation(self):
        geometry, view, result, settings = self.source_case()
        sizing = recommend_mesh(geometry, view, result, settings)
        def cancelled(*args):
            raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            refine_edges([0, 6, 12], [0, 6, 12], sizing, 2, 24, cancelled)

    def test_tiny_barrels_do_not_starve_source_targets_when_budget_is_tight(self):
        geometry, view, result, settings = inputs()
        view['components'][0]['bbox_mm'] = [5.4, 5.4, 6.6, 6.6]
        geometry['barrels'] = [{'id': 'via'+str(index), 'x_mm': .1+(index%20)*.08,
                               'y_mm': .1+(index//20)*.08, 'drill_mm': .01}
                              for index in range(400)]
        settings['auto_mesh_max_layer_cells'] = 2000
        sizing = recommend_mesh(geometry, view, result, settings)
        edges = [index*.5 for index in range(25)]
        x, y, selected = refine_edges(edges, edges, sizing, 2, 24)
        self.assertLessEqual((len(x)-1)*(len(y)-1)*2, 2000)
        self.assertNotIn('source: U1', selected['unresolved_features'])
        self.assertTrue(selected['budget_limited'])
        self.assertGreater(selected['unresolved_feature_count'], 0)

    def test_thin_sheet_auto_is_uniform_and_explicitly_limited(self):
        from quick_therm_plugin.thermal_network import solve_thermal_network
        from quick_therm_plugin.tests.test_thermal_network import view, result, settings
        solved = solve_thermal_network(view(), result(), settings(mesh_mode='auto'))
        sizing = solved['mesh']['automatic_sizing']
        self.assertEqual(solved['settings']['mesh_mode'], 'auto')
        self.assertAlmostEqual(sizing['minimum_cell_size_mm'], sizing['maximum_cell_size_mm'])
        self.assertTrue(any('uniform' in note for note in sizing['warnings']))
        self.assertLess(abs(solved['heat_balance']['residual_w']), 1e-5)

    def test_legacy_air_source_bounds_drive_thin_sheet_recommendation(self):
        from quick_therm_plugin.thermal_network import solve_thermal_network
        from quick_therm_plugin.tests.test_thermal_network import view, result, settings
        board, sources = view(), result()
        for row in sources['components']:
            row['heat_path'] = 'air'
        coarse = solve_thermal_network(board, sources, settings(mesh_mode='auto'))
        board['components'][0]['bbox_mm'] = [49.95, 49.95, 50.05, 50.05]
        fine = solve_thermal_network(board, sources, settings(mesh_mode='auto'))
        self.assertGreater(fine['board_field']['grid_cells_long_axis'], coarse['board_field']['grid_cells_long_axis'])
        self.assertLess(abs(fine['heat_balance']['residual_w']), 1e-5)

    def test_html_report_includes_selected_sizes_and_unmet_target_warning(self):
        from quick_therm_plugin.report import write_report
        geometry, view, result, settings = self.source_case()
        settings['auto_mesh_max_layer_cells'] = 1152
        network = solve_multilayer_thermal(geometry, view, result, settings)
        result.update(model='Board power inputs', board_c=None, assumptions=[],
                      coverage={'scoped': 1, 'solved': 0, 'excluded': []})
        result['components'][0].update(resistance_k_per_w=None, junction_c=None,
            rise_above_ambient_k=None)
        with tempfile.TemporaryDirectory() as directory:
            output = write_report(Path(directory)/'auto.html',
                                  {'quick_therm': result, 'thermal_network': network})
            document = Path(output['html']).read_text(encoding='utf-8')
        self.assertIn('Automatic mesh recommendation', document)
        self.assertIn('Unmet retained feature targets: 1', document)
        self.assertIn('not a convergence result', document)


if __name__ == '__main__':
    unittest.main()
