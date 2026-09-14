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
    with tempfile.TemporaryDirectory(prefix='wayricad-wheel-') as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        modules = ('copper_balancer_plugin.cli', 'mechanical_check_plugin.cli',
                   'visual_diff_plugin.kicad_vizdiff.cli')
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
from visual_diff_plugin.kicad_vizdiff.cli import write_report
output = Path(sys.argv[1]) / 'review.html'
write_report(output, {'pages': [], 'file': 'board.kicad_pcb'})
assert '__REPORT_DATA__' not in output.read_text(encoding='utf-8')
from mechanical_check_plugin import cli
assert cli.main(['--init-rules', str(Path(sys.argv[1])/'rules.json')]) == 0
assert (Path(sys.argv[1])/'mechanical_check_plugin/src/wayricad_mechanical/report_scene.js').is_file()
assert (Path(sys.argv[1])/'mechanical_check_plugin/resources/help.html').is_file()
'''
        subprocess.run([sys.executable, '-c', script, str(root)], cwd=root, check=True, timeout=30)
        print('Isolated wheel: report assets and mechanical rules export passed')


if __name__ == '__main__':
    main()
