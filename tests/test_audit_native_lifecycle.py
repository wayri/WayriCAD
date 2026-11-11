"""Lifecycle audit success requires both complete cycles and a clean native exit."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "audit_native_lifecycle", Path(__file__).resolve().parents[1] / "tools" / "audit_native_lifecycle.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


@pytest.mark.parametrize("code,state,timeout,expected", [
    (0, {"stage": "completed"}, False, "passed"),
    (0, {"stage": "shown"}, False, "incomplete"),
    (0, {}, False, "incomplete"),
    (1, {"stage": "completed"}, False, "python_error"),
    (1, {"status": "dependency_failure"}, False, "dependency_failure"),
    (1, {"status": "python_error"}, False, "python_error"),
    (0xC0000005, {"stage": "completed"}, False, "native_exit"),
    (-1073741819, {}, False, "native_exit"),
    (-11, {}, False, "native_exit"),
    (0, {"stage": "completed"}, True, "timeout"),
    (0xC0000005, {}, True, "timeout"),
])
def test_exit_classification(code, state, timeout, expected):
    assert audit.classify(code, state, timeout) == expected


def test_bounded_inventory_excludes_parent_owned_plugins():
    assert not {"quick_emerge_plugin", "quick_therm_plugin", "trace_impedance_plugin"} & audit.TARGETS.keys()
    assert len(audit.TARGETS) == 16
