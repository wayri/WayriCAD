"""The browser overview cannot expose removed generic editing operations."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_readonly_workspace_actions_and_rendering():
    node=os.environ.get('WAYRICAD_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Read-only workspace check requires Node.js')
    result=subprocess.run([node,str(Path(__file__).with_suffix('.cjs'))],
                          capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
