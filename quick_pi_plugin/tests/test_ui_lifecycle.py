"""A queued first-board read must not outlive a closed Quick PI window."""

from types import SimpleNamespace

import pytest

pytest.importorskip('wx')
pytest.importorskip('matplotlib')
from quick_pi_plugin.ui import QuickPIFrame


def test_deferred_inspection_and_job_ignore_closed_window():
    closed = SimpleNamespace(_closed=True, _closing=False)
    QuickPIFrame._inspect(closed)
    QuickPIFrame._job(closed, {'action': 'inspect'}, lambda value: value, 'Reading board')
