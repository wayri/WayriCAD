"""Run owned public-API bridge contracts in the existing Python CI suite."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_published_viewer_bridge_contracts():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node is required for the published viewer bridge contracts.')
    subprocess.run([node,'--test',str(Path(__file__).with_name('web_bridge_release.test.mjs'))],
                   check=True,capture_output=True,text=True,timeout=30,
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
