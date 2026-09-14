"""Secondary IPC menu action for the existing system workbench."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
if not (ROOT / "wayricad_runtime").is_dir():
    sys.path.insert(0, str(ROOT.parent))
from wayricad_runtime.launcher import main
if __name__ == "__main__":
    main(ROOT, action_class="InterboardHarnessPlugin")
