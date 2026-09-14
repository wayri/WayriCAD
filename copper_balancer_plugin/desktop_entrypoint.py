"""PCM entry point: launch the local saved-board workflow with KiCad Python."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from native_runner import launch

if __name__ == '__main__':
    raise SystemExit(launch())
