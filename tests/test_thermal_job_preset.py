"""The QuickTherm jobset preset remains explicit and report-only."""

from wayricad_runtime.job_presets import PRESETS, REQUIRED_VARIABLES
from wayricad_runtime.jobs import SCHEMA, validate


def test_quick_therm_jobset_uses_reviewed_config_and_limit_gate():
    step = PRESETS["thermal"][0]
    assert REQUIRED_VARIABLES["thermal"] == ("thermal_config",)
    assert step["argv"][:3] == ["${native_python}", "-m", "quick_therm_plugin.cli"]
    assert "--require-limits-pass" in step["argv"]
    assert step["outputs"] == ["thermal.json", "thermal.html"]
    validate({"schema": SCHEMA, "variables": {"thermal_config": "thermal.json"},
              "steps": PRESETS["thermal"]})
