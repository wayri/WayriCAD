import unittest
from quick_emerge_plugin.research_antennas import example_config, get_template
from quick_emerge_plugin.research_validation import compare_with_publication


class PaperRegistryTests(unittest.TestCase):
    def test_new_sources_expose_reconstruction_limits(self):
        for name in ('cheh-lin-2023-siw-dra', 'ma-2024-siw-horn'):
            source=get_template(name)
            self.assertIn('reconstruction', source['title'].lower())
            self.assertTrue(source['citation']['doi'].startswith('10.3390/'))
            config=example_config(name)
            self.assertEqual(config['advanced']['research_template'], name)
            self.assertGreater(config['advanced']['field_layers'], 1)
            result={'research':source, 'config':config, 'frequencies_hz':[1e9],
                    'port_count':1, 's_parameters':{'S11':[[0.1,0.0]]}}
            comparison=compare_with_publication(result)
            self.assertEqual(comparison['overall'], 'insufficient')
            self.assertTrue(any('assumptions' in check['check'] for check in comparison['checks']))

    def test_horn_samples_inside_pcb_guide_not_above_it(self):
        from quick_emerge_plugin.model import validate_config
        config=example_config('ma-2024-siw-horn')
        self.assertLess(config['field_z_mm'], 0)
        self.assertGreater(config['advanced']['field_z_min_mm'], -config['thickness_mm'])
        self.assertEqual(validate_config(config), config)
        config['field_z_mm']=-100
        with self.assertRaises(ValueError): validate_config(config)
