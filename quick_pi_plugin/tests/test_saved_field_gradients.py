"""Offline maps preserve native display data without changing solver evidence."""
import copy
import json
import re
import unittest

import numpy as np

from quick_pi_plugin.report import (METRICS, cell_values, gradient_surface,
                                    interactive_fields, result_scale, saved_field_surface)
from quick_pi_plugin.tests.test_report import bundle
from wayricad_runtime.field_render import field_palette


class SavedGradientTests(unittest.TestCase):
    def test_native_surface_palette_scale_and_evidence_unchanged(self):
        data = bundle()
        original = copy.deepcopy(data)
        indices = np.arange(len(data['mesh']['triangles']))
        for metric in ('drop', 'density', 'loss'):
            with self.subTest(metric=metric):
                field = saved_field_surface(data, 0, metric)
                xy, faces, values = gradient_surface(data['mesh'], data['result'], metric, indices)
                self.assertEqual(field['points'], xy.tolist())
                self.assertEqual(field['triangles'], faces.tolist())
                self.assertEqual(field['values'], values.tolist())
                self.assertEqual(field['palette'], field_palette(METRICS[metric][2]))
                self.assertEqual(field['limits'], list(result_scale(data, metric, 0)))
                self.assertEqual(field['style'], 'smooth')
        self.assertEqual(data, original)

    def test_manual_scale_and_solver_cells_are_preserved(self):
        data = bundle()
        data['view_settings'] = {'scale_mode': 2, 'field_style': 'cells',
                                 'manual': {'metric': 'drop', 'limits': [0, 20]}}
        field = saved_field_surface(data, 0, 'drop')
        self.assertEqual(field['limits'], [0, 20])
        self.assertEqual(field['values'], np.repeat(cell_values(data['mesh'], data['result'], 'drop'), 3).tolist())
        self.assertEqual(field['style'], 'cells')

    def test_export_keeps_full_triangles_and_exact_cell_probes(self):
        data = bundle()
        html = interactive_fields(data, 0)
        payloads = re.findall(r',data=(.*?);\s*const SavedField', html, re.S)
        self.assertEqual(len(payloads), 3)
        for metric, payload in zip(('drop', 'density', 'loss'), payloads):
            saved = json.loads(payload)
            self.assertEqual(saved['field'], saved_field_surface(data, 0, metric))
            self.assertEqual([row[2] for row in saved['rows']], cell_values(data['mesh'], data['result'], metric).tolist())
            self.assertEqual(len(saved['polygons']), len(data['mesh']['triangles']))

    def test_unknown_cells_and_wrong_layer_have_no_display_surface(self):
        data = bundle()
        self.assertIsNone(saved_field_surface(data, 99, 'loss'))
        data['result']['cell_power_W'] = [None] * len(data['mesh']['triangles'])
        self.assertIsNone(saved_field_surface(data, 0, 'loss'))
