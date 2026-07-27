import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from extract_pins_plugin import cli


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class KiWayCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "extract_pins_plugin", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_help_lists_required_top_level_commands(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("inspect", "extract", "crosslink", "validate", "report", "jobset-run", "benchmark", "dependencies", "test"):
            self.assertIn(command, result.stdout)

    def test_jobset_run_builds_native_kicad_command(self):
        project = FIXTURES / "sample.kicad_pro"
        jobset = FIXTURES / "release.kicad_jobset"
        project.write_text("{}", encoding="utf-8")
        jobset.write_text("{}", encoding="utf-8")
        try:
            with mock.patch.object(cli, "find_kicad_cli", return_value="kicad-cli"), mock.patch.object(cli.subprocess, "run") as run:
                run.return_value.returncode = 0
                result = cli.main([
                    "jobset-run", str(project), "--file", str(jobset),
                    "--destination", "Manufacturing", "--stop-on-error",
                ])
            self.assertEqual(result, 0)
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ["kicad-cli", "jobset", "run", "--stop-on-error"])
            self.assertIn("--output", command)
            self.assertEqual(command[-1], str(project.resolve()))
            self.assertEqual(run.call_args.kwargs["cwd"], str(project.parent.resolve()))
        finally:
            project.unlink(missing_ok=True)
            jobset.unlink(missing_ok=True)

    def test_jobset_run_rejects_wrong_input_type(self):
        result = self.run_cli("jobset-run", str(FIXTURES / "simple_hierarchy.xml"), "--file", "missing.kicad_jobset")
        self.assertEqual(result.returncode, 2)
        self.assertIn(".kicad_pro", result.stderr)

    def test_report_help_accepts_crosslink_rules_file(self):
        result = self.run_cli("report", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--rules-file", result.stdout)

    def test_dependencies_emits_full_suite_health_json(self):
        result = self.run_cli("dependencies")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("runtime", payload)
        self.assertEqual(len(payload["suite"]), 9)
        self.assertEqual(
            {row["key"] for row in payload["dependencies"]},
            {"networkx", "markdown", "matplotlib", "pillow"},
        )

    def test_inspect_json_is_deterministic_and_preserves_sheet_aliases(self):
        result = self.run_cli(
            "inspect",
            str(FIXTURES / "simple_hierarchy.xml"),
            "--board-sequence",
            "DEMO_CTRL,DEMO_SENSOR",
            "--sheet-alias",
            "ADCS IMU:/Main/ADCS/*:U*",
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["component_count"], 4)
        self.assertIn("ADCS IMU", {row["Sheet"] for row in payload["sheets"]})

    def test_extract_tm_tc_finds_source_destination_and_type(self):
        result = self.run_cli(
            "extract",
            str(FIXTURES / "simple_hierarchy.xml"),
            "--board-sequence",
            "DEMO_CTRL,DEMO_SENSOR",
            "--kind",
            "tm-tc",
            "--consolidate",
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        types = {row["Type"] for row in rows}
        self.assertEqual(types, {"TD", "TM"})
        self.assertTrue(all(row["Source Board"] == "DEMO_CTRL" for row in rows))

    def test_extract_controller_map_requires_explicit_active_opt_in(self):
        xml = """<?xml version="1.0"?>
<export>
  <components>
    <comp ref="U1"><value>Controller</value></comp>
    <comp ref="Q1"><value>MOSFET</value></comp>
    <comp ref="J1"><value>Connector</value></comp>
  </components>
  <nets>
    <net code="1" name="DRIVE">
      <node ref="U1" pin="4" pinfunction="GPIO"/>
      <node ref="Q1" pin="1" pinfunction="D"/>
    </net>
    <net code="2" name="SWITCHED">
      <node ref="Q1" pin="2" pinfunction="S"/>
      <node ref="J1" pin="7" pinfunction="OUTPUT"/>
    </net>
  </nets>
</export>
"""
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as handle:
            handle.write(xml)
            path = Path(handle.name)
        try:
            disabled = self.run_cli(
                "extract", str(path), "--kind", "controller-map",
                "--path-rule", "Q1 | D-S | active | verify MOSFET state",
                "--format", "json",
            )
            enabled = self.run_cli(
                "extract", str(path), "--kind", "controller-map",
                "--path-rule", "Q1 | D-S | active | verify MOSFET state",
                "--include-active-paths", "--format", "json",
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertEqual(json.loads(disabled.stdout), [])
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        rows = json.loads(enabled.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Status"], "Conditional")
        self.assertEqual(rows[0]["Pin Transitions"], "Q1.1->Q1.2")

    def test_crosslink_wildcard_rule_outputs_svg_and_excludes_power_by_default(self):
        result = self.run_cli(
            "crosslink",
            str(FIXTURES / "board_a.csv"),
            str(FIXTURES / "board_b.md"),
            "--project",
            "DEMO_CTRL",
            "--project",
            "DEMO_SENSOR",
            "--rules",
            "Board prefix | wildcard | DEMO_CTRL_* | DEMO_SENSOR_*",
            "--no-exact",
            "--no-normalized",
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["Signal Key"] for row in rows}, {"SPI1_CLK", "SPI1_MOSI"})

    def test_validate_fails_when_required_tm_consumer_is_missing(self):
        result = self.run_cli(
            "validate",
            str(FIXTURES / "simple_hierarchy.xml"),
            "--board-sequence",
            "DEMO_CTRL",
            "--require-tm-consumer",
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 3)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "fail")

    def test_benchmark_emits_machine_readable_result(self):
        result = self.run_cli("benchmark", "--nets", "100", "--boards", "3", "--threshold-ms", "3000")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["links"], 100)


if __name__ == "__main__":
    unittest.main()
