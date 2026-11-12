from pathlib import Path
import unittest
from build_pcm import plugin_files


class FabricationPackageContentTests(unittest.TestCase):
    def test_offline_net_compare_examples_and_help_ship_without_test_code(self):
        base = Path(__file__).resolve().parents[1] / 'manufacturing_readiness_plugin'
        names = {path.relative_to(base).as_posix() for path in plugin_files(base)}
        for required in ('fab_compare.py', 'fab_compare_ui.py', 'fab_compare_report.py',
                         'fab_reference.py', 'fab_compare_help.html',
                         'examples/fab-reference.json', 'examples/fab-intentional-short.json'):
            self.assertIn(required, names)
        self.assertFalse(any('tests' in Path(name).parts for name in names))


if __name__ == '__main__':
    unittest.main()
