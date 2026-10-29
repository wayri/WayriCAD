"""Refinement pass semantics and safe stopping; numerical proof is separate."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from quick_emerge_plugin.model import validate_config
from quick_emerge_plugin.refinement import refine_mesh


class RefinementTests(unittest.TestCase):
    def model(self, counts):
        model = SimpleNamespace(mesh=SimpleNamespace(n_tets=100))
        changes = iter(counts)
        def advance(**kwargs):
            model.mesh.n_tets = next(changes)
        model.adaptive_mesh_refinement = Mock(side_effect=advance)
        return model

    def test_exact_requested_public_passes(self):
        model = self.model([120, 144])
        config = validate_config({'adaptive_steps': 2, 'max_tets': 150})
        refine_mesh(model, config, Mock())
        calls = model.adaptive_mesh_refinement.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(model.mesh.n_tets, 144)
        for call in calls:
            self.assertEqual(call.kwargs, dict(max_steps=2, minimum_steps=2,
                min_refined_passes=2, growth=0.2, convergence=0.02,
                max_tets=150, frequency=(config['f_start_hz']+config['f_stop_hz'])/2,
                show_mesh=False))

    def test_budget_or_unchanged_mesh_stops_remaining_passes(self):
        for count, message in [(151, 'limit'), (100, 'No finer mesh')]:
            with self.subTest(count=count):
                model = self.model([count])
                with self.assertRaisesRegex(ValueError, message):
                    refine_mesh(model, validate_config({'adaptive_steps': 3, 'max_tets': 150}), Mock())
                self.assertEqual(model.adaptive_mesh_refinement.call_count, 1)

    def test_disabled_refinement_does_not_call_solver(self):
        model = self.model([])
        refine_mesh(model, validate_config({}), Mock())
        model.adaptive_mesh_refinement.assert_not_called()
