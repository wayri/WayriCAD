"""Exercise imported CLI entrypoints and report assets from an isolated wheel."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    wheel = parser.parse_args().wheel.resolve()
    source_root = Path(__file__).resolve().parents[1]
    active_plugins = {
        path.name for path in source_root.glob('*_plugin')
        if (path / 'metadata.json').is_file()
    }
    with tempfile.TemporaryDirectory(prefix='wayricad-wheel-') as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(wheel) as archive:
            if any(name.startswith(('build/', 'dist/', '.validation/')) for name in archive.namelist()):
                raise RuntimeError('Wheel contains generated build or private validation directories.')
            stale_plugins = {
                Path(name).parts[0] for name in archive.namelist()
                if Path(name).parts and Path(name).parts[0].endswith('_plugin')
                and Path(name).parts[0] not in active_plugins
            }
            if stale_plugins:
                raise RuntimeError(
                    'Wheel contains inactive plugin files: ' + ', '.join(sorted(stale_plugins))
                )
            archive.extractall(root)
        modules = ('wayricad_runtime.cli', 'trace_impedance_plugin.cli', 'copper_balancer_plugin.cli', 'mechanical_check_plugin.cli',
                   'embed_3d_plugin.__main__', 'quick_pi_plugin.cli', 'signal_integrity_advisor_plugin.cli')
        for module in modules:
            script = ('import importlib,sys;sys.path.insert(0,sys.argv[1]);'
                      'module=importlib.import_module(sys.argv[2]);'
                      'sys.argv=[sys.argv[2],"--help"];raise SystemExit(module.main())')
            result = subprocess.run([sys.executable, '-c', script, str(root), module],
                                    cwd=root, capture_output=True, text=True, timeout=30)
            if result.returncode or 'usage:' not in result.stdout.lower():
                raise RuntimeError(module + ': ' + result.stdout + result.stderr)
            print(module + ': isolated CLI help passed')
        script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from argparse import Namespace
from wayricad_runtime.cli import execute
settings=execute(Namespace(kind='fanout',operation='settings',board=None))
assert 'Custom-angle spread' in settings['choices']['pattern']
assert 'PCIe' in settings['profiles']
from mechanical_check_plugin import cli
assert cli.main(['--init-rules', str(Path(sys.argv[1])/'rules.json')]) == 0
assert (Path(sys.argv[1])/'mechanical_check_plugin/src/wayricad_mechanical/report_scene.js').is_file()
assert (Path(sys.argv[1])/'mechanical_check_plugin/resources/help.html').is_file()
from protocol_constraint_composer_plugin.constraint_studio.help_system import HelpLibrary
assert len(HelpLibrary().topics) >= 100
assert (Path(sys.argv[1])/'protocol_constraint_composer_plugin/help-workflow.png').is_file()
for relative in ('quick_pi_plugin/decoupling', 'signal_integrity_advisor_plugin/return_path', 'signal_integrity_advisor_plugin/test_points'):
    folder=Path(sys.argv[1])/relative
    for asset in ('__init__.py','help.html','help-workflow.png','icon.png'):
        assert (folder/asset).is_file(), str(folder/asset)
from quick_pi_plugin.decoupling.analysis import analyze_decoupling
from signal_integrity_advisor_plugin.return_path.analysis import ReturnPathAnalyzer
from signal_integrity_advisor_plugin.test_points.fixture import FixturePoint

'''
        subprocess.run([sys.executable, '-c', script, str(root)], cwd=root, check=True, timeout=30)
        print('Isolated wheel: report assets and mechanical rules export passed')


if __name__ == '__main__':
    main()
