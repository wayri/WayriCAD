"""Create an original two-revision sample and render both full-page comparisons."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fixtures import schematic, board
from kicad_vizdiff.git import git
from kicad_vizdiff.cli import main

destination = Path(sys.argv[1] if len(sys.argv) > 1 else '.validation/visual-diff-demo').resolve()
repo = destination / 'repository'
if repo.exists():
    raise SystemExit(f'Refusing to replace an existing demo: {repo}')
repo.mkdir(parents=True)
git(repo, 'init')
for changed in (False, True):
    (repo / 'sensor.kicad_sch').write_text(schematic(changed), encoding='utf-8')
    (repo / 'sensor.kicad_pcb').write_text(board(changed), encoding='utf-8')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Demo', '-c', 'user.email=demo@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'Adjust sensor' if changed else 'Initial sensor')
for ext, name in [('kicad_sch', 'schematic'), ('kicad_pcb', 'pcb')]:
    code = main(['diff', f'sensor.{ext}', '--repo', str(repo), '--base', 'HEAD~1', '--head', 'HEAD',
                 '--layers', 'F.Cu,F.Silkscreen,Edge.Cuts', '--output', str(destination / f'{name}.html')])
    if code:
        raise SystemExit(code)
