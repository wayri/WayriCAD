"""KiCad IPC entry point; shared runtime is bundled by build_pcm.py."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
if not (ROOT / "wayricad_runtime").is_dir():
    sys.path.insert(0, str(ROOT.parent))
from wayricad_runtime.launcher import main
if __name__ == "__main__":
    main(ROOT)
