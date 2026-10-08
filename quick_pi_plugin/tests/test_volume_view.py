"""Regression checks for bounded, layer-aware 3D result displays."""

import unittest

from quick_pi_plugin.volume_view import layer_names, sampled_cells


def sample_bundle():
    return {
        'geometry': {'layers': [
            {'name': 'F.Cu', 'z_mm': .02, 'thickness_mm': .04, 'polygons': [1]},
            {'name': 'B.Cu', 'z_mm': 1.02, 'thickness_mm': .04, 'polygons': [1]}]},
        'mesh': {'tetrahedra': [[0, 1, 2, 3], [1, 2, 3, 4], [2, 3, 4, 5]]},
        'result': {
            'cell_centroid_mm': [[1, 2, .02], [1, 2, .5], [1, 2, 1.02]],
            'cell_J_A_mm2': [[3, 4, 0], None, [0, 0, 2]],
            'cell_power_W': [.4, None, .6],
            'cell_volume_mm3': [.2, .2, .3],
            'potential_V': [1, 1, 1, 1, None, 0],
        },
    }


class VolumeViewTests(unittest.TestCase):
    def test_layer_filter_and_unknowns(self):
        bundle = sample_bundle()
        self.assertEqual(layer_names(bundle), ['All copper', 'F.Cu', 'B.Cu', 'Interlayer barrels'])
        xyz, values, count = sampled_cells(bundle, 'F.Cu')
        self.assertEqual(count, 1)
        self.assertEqual(xyz.tolist(), [[1, 2, .02]])
        self.assertEqual(values.tolist(), [5.])
        self.assertEqual(sampled_cells(bundle, 'Interlayer barrels')[2], 0)
        self.assertEqual(sampled_cells(bundle, 'B.Cu', 'loss_density')[1].tolist(), [2.])

    def test_offline_volume_report_keeps_complete_json(self):
        import json,tempfile
        from pathlib import Path
        from quick_pi_plugin.volume_view import write_volume_report
        bundle=sample_bundle()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'volume.html';write_volume_report(path,bundle)
            html=path.read_text(encoding='utf-8')
            self.assertEqual(html.count('<canvas '),3)
            self.assertIn('Shift-drag to pan',html)
            self.assertIn('Display movement does not change',html)
            self.assertEqual(json.loads(path.with_suffix('.json').read_text()),bundle)

    def test_display_limit_does_not_change_model(self):
        bundle = sample_bundle()
        _, values, total = sampled_cells(bundle, limit=1)
        self.assertEqual(total, 2)
        self.assertEqual(len(values), 1)
        self.assertEqual(len(bundle['result']['cell_centroid_mm']), 3)
        with self.assertRaisesRegex(ValueError, 'Unknown copper layer'):
            sampled_cells(bundle, 'In99.Cu')
        with self.assertRaisesRegex(ValueError, 'Unknown 3D field'):
            sampled_cells(bundle, quantity='bogus')


if __name__ == '__main__':
    unittest.main()
