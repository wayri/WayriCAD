import json
import subprocess
import sys
import unittest
from pathlib import Path


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
        for command in ("inspect", "extract", "crosslink", "validate", "report", "benchmark", "dependencies", "test"):
            self.assertIn(command, result.stdout)

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
