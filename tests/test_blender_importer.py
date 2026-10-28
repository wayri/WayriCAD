"""Bounded, solver-independent Blender scene contracts."""
import copy
import unittest

from wayricad_runtime.blender_import import (
    SCHEMA, UNKNOWN, camera_scale, held_sample, object_group, scalar_color,
    scalar_range, shared_ranges, validate_scene, wire_envelope,
)


def scene():
    return {'schema': SCHEMA, 'objects': [{
        'name': 'Sheet', 'vertices_mm': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        'faces': [[0, 1, 2]], 'field': {
            'name': 'Temperature', 'unit': 'C', 'values': [20],
            'frames': [{'time_s': 0, 'values': [25]}, {'time_s': 0.3, 'values': [40]}],
        },
    }]}


class BlenderSceneTests(unittest.TestCase):
    def test_timeline_and_fixed_range_cover_all_stored_states(self):
        data = scene()
        self.assertEqual(validate_scene(data), [0, 0.3])
        self.assertEqual(scalar_range(data['objects'][0]['field']), (20, 40))

    def test_samples_hold_actual_states_without_interpolation(self):
        field = scene()['objects'][0]['field']
        self.assertEqual(held_sample(field, -1), [20])
        self.assertEqual(held_sample(field, 0.15), [25])
        self.assertEqual(held_sample(field, 0.3), [40])

    def test_camera_fits_landscape_board_without_empty_sidebar(self):
        self.assertAlmostEqual(camera_scale((0, 0, 0), (0.2, 0.1, 0)), 0.224)
        self.assertAlmostEqual(camera_scale((0, 0, 0), (0.1, 0.2, 0)), 0.2986666666666667)

    def test_component_envelopes_do_not_obscure_electrical_field_renders(self):
        proxy = {'properties': {'reference': 'U1', 'geometry_meaning': 'Footprint bounding envelope; illustrative height'}}
        solid = {'properties': {'reference': 'U2', 'geometry_meaning': 'Saved triangle mesh'}}
        self.assertEqual(object_group(proxy), 'components')
        self.assertTrue(wire_envelope(proxy, 'pi'))
        self.assertTrue(wire_envelope(proxy, 'si'))
        self.assertFalse(wire_envelope(proxy, 'therm'))
        self.assertFalse(wire_envelope(solid, 'pi'))
        self.assertEqual(object_group({'field': {'values': [1]}}), 'fields')
        self.assertEqual(object_group({}), 'board')

    def test_unknown_is_not_zero_or_imputed(self):
        self.assertEqual(scalar_color(None, (0, 1)), UNKNOWN)
        self.assertEqual(scalar_range({'values': [None], 'frames': []}), None)
        self.assertEqual(scalar_color(4, (4, 4)), scalar_color(0.5, (0, 1)))

    def test_components_share_temperature_scale_including_all_frames(self):
        data = scene()
        cool = data['objects'][0]
        cool['field']['values'] = [45]
        cool['field']['frames'] = []
        hot = copy.deepcopy(cool)
        hot['field']['values'] = [100]
        hot['field']['frames'] = [{'time_s': 0, 'values': [120]}]
        unknown = copy.deepcopy(cool)
        unknown['field']['values'] = [None]
        data['objects'].extend([hot, unknown])
        scales = shared_ranges(data)
        self.assertEqual(scales, {('Temperature', 'C'): (45, 120)})
        self.assertNotEqual(scalar_color(45, scales[('Temperature', 'C')]),
                            scalar_color(100, scales[('Temperature', 'C')]))

    def test_different_quantities_or_units_never_share_scale(self):
        data = scene()
        other = copy.deepcopy(data['objects'][0])
        other['field']['unit'] = 'K'
        other['field']['values'] = [300]
        other['field']['frames'] = []
        empty = copy.deepcopy(other)
        empty['field'] = {'name': 'Unknown voltage', 'unit': 'V', 'values': [None]}
        data['objects'].extend([other, empty])
        self.assertEqual(shared_ranges(data), {
            ('Temperature', 'C'): (20, 40), ('Temperature', 'K'): (300, 300),
            ('Unknown voltage', 'V'): None,
        })

    def test_invalid_indices_and_array_lengths_rejected(self):
        for mutate in (
            lambda d: d['objects'][0]['faces'][0].__setitem__(1, 8),
            lambda d: d['objects'][0]['field'].__setitem__('values', []),
            lambda d: d['objects'][0]['vertices_mm'][0].__setitem__(0, float('nan')),
            lambda d: d['objects'][0]['faces'][0].__setitem__(0, True),
        ):
            data = scene(); mutate(data)
            with self.assertRaises(ValueError): validate_scene(data)

    def test_frame_order_and_finite_values_rejected(self):
        for invalid in (-1, 0, float('inf')):
            data = scene()
            data['objects'][0]['field']['frames'][1]['time_s'] = invalid
            with self.assertRaises(ValueError): validate_scene(data)

    def test_mismatched_trace_and_empty_scene_rejected(self):
        for data in ({'schema': SCHEMA}, {'schema': SCHEMA, 'traces': [
            {'time_s': [0, 1], 'values': [4]},
        ]}):
            with self.assertRaises(ValueError): validate_scene(data)

    def test_validating_does_not_modify_evidence(self):
        data = scene(); original = copy.deepcopy(data)
        validate_scene(data)
        self.assertEqual(data, original)

    def test_trace_preserves_two_sides_of_instantaneous_event(self):
        data = {'schema': SCHEMA, 'traces': [
            {'name': 'Load current', 'unit': 'A', 'time_s': [0, 1, 1, 2],
             'values': [0.1, 0.1, 1, 1]},
        ]}
        self.assertEqual(validate_scene(data), [])
        data['traces'][0]['time_s'] = [0, 1, 0.5, 2]
        with self.assertRaises(ValueError): validate_scene(data)


if __name__ == '__main__':
    unittest.main()
