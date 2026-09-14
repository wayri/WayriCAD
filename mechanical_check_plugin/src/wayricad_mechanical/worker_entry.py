"""Bootstrap for isolated Python distributions that ignore PYTHONPATH."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
module = sys.argv.pop(1)
runpy.run_module('wayricad_mechanical.' + module, run_name='__main__')
