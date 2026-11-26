"""Trace width estimates against a closed-form strip and ambiguous copper."""

import copy
import math
import unittest

from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip
from quick_pi_plugin.width_guidance import recommend_trace_widths


class WidthGuidanceTests(unittest.TestCase):
    def model(self, copper_width=1., saved_width=1., budget=.008):
        mesh, source, sink = strip(width=copper_width, ny=6)
        mesh['triangle_layer'] = [0]*len(mesh['triangles'])
        mesh['geometry'] = {'layers': [{'id': 0, 'name': 'F.Cu'}],
                            'mesh_features': [{'kind': 'track', 'id': 'trace-uuid',
                                               'layer': '0', 'width_mm': saved_width,
                                               'start_mm': [0., copper_width/2],
                                               'end_mm': [10., copper_width/2]}]}
        result = solve(mesh, source, None, source_voltage=3.3,
                       sinks=[{'nodes': sink, 'current_A': 2., 'min_voltage_V': 3.3-budget}])
        return mesh, result

    def test_failing_strip_matches_independent_estimate_and_resolves_limit(self):
        mesh, result = self.model()
        original = copy.deepcopy(result)
        evidence = recommend_trace_widths(mesh, result)
        self.assertEqual(evidence['status'], 'available', evidence)
        row = evidence['rows'][0]
        self.assertEqual(row['source_ids'], ['trace-uuid'])
        self.assertAlmostEqual(row['sampled_current_A'], 2., places=8)
        self.assertAlmostEqual(row['existing_width_mm'], 1., places=8)
        self.assertAlmostEqual(row['voltage_headroom_V'], .008-result['voltage_drop_V'], places=10)

        total_drop = 2.*1.724e-8*.01/(.001*.000035)
        sampled = total_drop * row['sampled_length_mm']/10.
        other = total_drop-sampled
        self.assertAlmostEqual(row['sampled_drop_V'], sampled, places=10)
        self.assertAlmostEqual(row['minimum_width_mm'], sampled/(.008-other), places=8)
        self.assertAlmostEqual(row['recommended_width_mm'], sampled/(.0072-other), places=8)
        self.assertAlmostEqual(row['recommended_sink_voltage_V'], 3.3-.0072, places=10)

        # A real re-solve with the whole straight trace widened should pass the
        # target voltage that the central-span-only estimate prescribed.
        wider, _ = self.model(copper_width=row['recommended_width_mm'],
                              saved_width=row['recommended_width_mm'])
        start = [i for i, point in enumerate(wider['points_mm']) if point[0] == 0.]
        end = [i for i, point in enumerate(wider['points_mm']) if point[0] == 10.]
        rerun = solve(wider, start, end, source_voltage=3.3, sink_current=2.)
        self.assertGreaterEqual(rerun['sink_voltage_V'], row['recommended_sink_voltage_V'])
        self.assertEqual(result, original)

    def test_margin_screen_and_explicit_current_limit(self):
        mesh, result = self.model(budget=.02)
        self.assertEqual(recommend_trace_widths(mesh, result)['status'], 'not_needed')
        evidence = recommend_trace_widths(mesh, result, minimum_voltage_V=3.3-.010)
        self.assertEqual(evidence['status'], 'available', evidence)
        row = evidence['rows'][0]
        self.assertEqual(row['minimum_width_mm'], 1.)
        self.assertGreater(row['recommended_width_mm'], 1.)
        self.assertGreater(row['voltage_headroom_V'], 0.)

    def test_no_credible_width_when_other_drops_use_declared_budget(self):
        mesh, result = self.model(budget=.002)
        row = recommend_trace_widths(mesh, result)['rows'][0]
        self.assertEqual(row['status'], 'other_drop_exceeds_limit')
        self.assertLess(row['remaining_trace_budget_V'], 0)
        self.assertIsNone(row['recommended_width_mm'])

    def test_saved_trace_direction_does_not_change_recommendation(self):
        mesh, result = self.model()
        original = recommend_trace_widths(mesh, result)['rows'][0]
        feature = mesh['geometry']['mesh_features'][0]
        feature['start_mm'], feature['end_mm'] = feature['end_mm'], feature['start_mm']
        reversed_trace = recommend_trace_widths(mesh, result)['rows'][0]
        for key in ('recommended_width_mm', 'minimum_width_mm', 'sampled_current_A', 'sampled_drop_V'):
            # The five sample stations deliberately avoid coincident mesh
            # edges. Endpoint reversal changes the sampled interval position,
            # not its span or the uniform strip's numerical prediction.
            self.assertAlmostEqual(reversed_trace[key], original[key], places=8)

    def test_adjacent_plane_copper_and_partial_current_are_not_trace_widths(self):
        mesh, result = self.model(copper_width=2.)
        result['fusing']['bottlenecks'] = [{'kind': 'sheet', 'source_ids': ['trace-uuid']}]
        evidence = recommend_trace_widths(mesh, result, minimum_voltage_V=3.3-.004)
        self.assertEqual((evidence['status'], evidence['rows']), ('unavailable', []))

        mesh, result = self.model()
        result['cell_sheet_current_A_mm'] = [[axis/2 for axis in row] for row in result['cell_sheet_current_A_mm']]
        evidence = recommend_trace_widths(mesh, result)
        self.assertEqual((evidence['status'], evidence['rows']), ('unavailable', []))

    def test_known_unsupported_modes_and_missing_limits_are_explicit(self):
        mesh, result = self.model()
        result['sinks'][0]['min_voltage_V'] = 0.
        self.assertIn('positive minimum', recommend_trace_widths(mesh, result)['reason'])
        result['operating_mode'] = 'constant_power_loads'
        self.assertEqual(recommend_trace_widths(mesh, result)['status'], 'unavailable')
        result.pop('operating_mode')
        self.assertEqual(recommend_trace_widths(mesh, result, minimum_voltage_V=math.nan)['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
