"""Open the QuickTherm workspace from KiCad's PCB Editor."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from desktop_entrypoint import main


if __name__ == '__main__':
    raise SystemExit(main(entrypoint='quick_therm_entrypoint.py', start_tab='QuickTherm'))
