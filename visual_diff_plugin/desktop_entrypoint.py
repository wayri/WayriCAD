"""KiCad IPC launches this independent, local saved-file comparison window."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from kicad_vizdiff.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
