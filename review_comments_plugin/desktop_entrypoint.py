"""Open Review for a saved board supplied by KiCad's legacy All tools menu."""
from pathlib import Path
import importlib
import sys
import types

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
if not (root / 'wayricad_runtime').is_dir():
    sys.path.insert(0, str(root.parent))
package = types.ModuleType('wayricad_review_desktop')
package.__path__ = [str(root)]
sys.modules[package.__name__] = package

if __name__ == '__main__':
    cli = importlib.import_module(package.__name__ + '.cli')
    raise SystemExit(cli.main(['open', *sys.argv[1:]]))
