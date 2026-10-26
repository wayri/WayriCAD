"""Large-board exports retain interactive evidence without unbounded print work."""
import unittest
import json
from pathlib import Path
import tempfile
from quick_therm_plugin.report import printable_modes


class ReportBudgetTests(unittest.TestCase):
    def test_component_only_report_without_board_network(self):
        from quick_therm_plugin.quick_therm import simulate_steady_state
        from quick_therm_plugin.report import write_report
        thermal = simulate_steady_state([
            {'reference': 'U1', 'values': {'power_w': 1., 'theta_ja_air_k_per_w': 40.}}
        ], environment='air', ambient_c=20.)
        bundle = {'quick_therm': thermal, 'thermal_network': None,
                  'board_thermal_view': {}, 'temperature_limits': None}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'thermal.html'
            write_report(path, bundle)
            document = path.read_text(encoding='utf-8')
            self.assertIn('Not solved; component estimates only', document)
            self.assertIn('Not verified', document)
            self.assertIsNone(json.loads(path.with_suffix('.json').read_text())['thermal_network'])

    def test_large_board_keeps_three_primary_snapshots(self):
        view={'components':[{'reference':'U'+str(i)} for i in range(1006)],'drills':[{}]*1361}
        network={'layers':[{'name':'Cu'+str(i)} for i in range(12)]}
        modes=printable_modes(view,network)
        self.assertEqual(modes,['Top board model','Bottom board model','Component temperature comparison'])
        self.assertEqual(len(network['layers']),12)
        self.assertEqual(len(view['components']),1006)
        extended=printable_modes(view,network,{'extended_snapshots':True})
        self.assertIn('3D overview',extended)
        self.assertIn('Layer model: Cu11',extended)

    def test_small_board_preserves_existing_extended_snapshots(self):
        self.assertIn('3D overview',printable_modes({'components':[]},None))
        self.assertEqual(len(printable_modes({},None,{'extended_snapshots':False})),3)

    def test_invalid_export_options_fail_instead_of_inventing_modes(self):
        for settings in ({'unknown':True},{'extended_snapshots':1},[],False):
            with self.subTest(settings=settings),self.assertRaises(ValueError):printable_modes({},None,settings)


if __name__=='__main__':unittest.main()
