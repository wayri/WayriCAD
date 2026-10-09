"""Exercise the shipped bridge in Node without a browser or a live PCB editor."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_visual_bridge_response_loss_and_focus_concurrency():
    node = os.environ.get('WAYRICAD_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Visual bridge regression requires Node.js.')
    result = subprocess.run([node, str(Path(__file__).with_suffix('.cjs'))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'focus concurrency passed' in result.stdout
