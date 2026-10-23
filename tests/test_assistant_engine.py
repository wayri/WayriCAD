"""Behavioral checks for local interpretation and isolated read-only execution."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from wayricad_runtime import assistant as engine


QUERY = "Calculate microstrip impedance width 0.2 mm height 0.1 mm er 4.2"


class AssistantEngineTests(unittest.TestCase):
    def test_common_intents_and_clarifications(self):
        examples = {
            "simulate power integrity": "quick-pi.solve",
            "check signal integrity": "signal-integrity.screen",
            "analyze board temperature": "quick-therm.analyze",
            "check mechanical clearances": "mechanical-check.analyze",
            "place reference labels": "silkscreen-label-placer.preview",
            "preview connector fanout": "fanout-generator.preview",
            "arrange components": "component-arranger.preview",
            "calculate microstrip impedance": "trace-impedance.cross-section",
        }
        for query, action in examples.items():
            with self.subTest(query=query):
                plan = engine.propose(query)
                self.assertEqual(plan["status"], "needs_input")
                self.assertEqual(plan["steps"][0]["action"], action)
                self.assertTrue(plan["questions"])
        self.assertEqual(
            engine.propose("run an arbitrary shell executable")["status"], "unsupported"
        )

    def test_units_exact_net_and_missing_board(self):
        plan = engine.propose(
            'Check voltage drop on net "/Power/VCC" from J1.1 to U3.2 at 3.3 V drawing 250 mA'
        )
        values = plan["steps"][0]["params"]
        self.assertEqual(values["net"], "/Power/VCC")
        self.assertEqual(values["source"], "J1.1")
        self.assertEqual(values["sink"], "U3.2")
        self.assertEqual(values["voltage"], 3.3)
        self.assertEqual(values["current"], 0.25)
        self.assertEqual([q["key"] for q in plan["questions"]], ["0.board"])

    def test_answers_invalid_numeric_and_optional_boolean(self):
        plan = engine.propose(QUERY, answers={"width_mm": "not numeric"})
        self.assertEqual(plan["status"], "needs_input")
        self.assertEqual([q["key"] for q in plan["questions"]], ["0.width_mm"])
        ready = engine.propose(QUERY, answers={"0.width_mm": "0.3"})
        self.assertEqual(ready["steps"][0]["params"]["width_mm"], 0.3)
        boolean = engine.propose(
            "preview connector fanout", answers={"add_vias": "false"}
        )
        self.assertIs(boolean["steps"][0]["params"]["add_vias"], False)

    def test_ambiguous_choice_and_bounded_multi_task(self):
        plan = engine.propose("show board analytics")
        self.assertEqual(plan["status"], "ambiguous")
        chosen = engine.propose(
            "show board analytics", answers={"action": "bom-studio.info"}
        )
        self.assertEqual(chosen["steps"][0]["action"], "bom-studio.info")
        multi = engine.propose(QUERY + "; list available tools")
        self.assertEqual(multi["status"], "ready")
        self.assertEqual(len(multi["steps"]), 2)
        bad = engine.propose(QUERY + "; execute arbitrary shell")
        self.assertNotEqual(bad["status"], "ready")
        with self.assertRaises(ValueError):
            engine.propose(";".join(["list available tools"] * 9))

    def test_tampering_and_invalid_parameters_rejected(self):
        plan = engine.propose(QUERY)
        plan["steps"][0]["params"]["width_mm"] = 0.4
        with self.assertRaisesRegex(ValueError, "changed after"):
            engine.validate_plan(plan)
        engine._seal(plan)
        plan["steps"][0]["params"]["arbitrary_switch"] = "--apply"
        engine._seal(plan)
        with self.assertRaisesRegex(ValueError, "Unknown action parameters"):
            engine.validate_plan(plan)

    def test_source_edits_invalidate_plan_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            board = Path(temp) / "board.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            plan = engine.propose("list available tools", {"board": str(board)})
            engine.validate_plan(plan)
            board.write_text("(kicad_pcb (version 1))", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Saved inputs changed"):
                engine.run_plan(plan, Path(temp) / "results")
            self.assertFalse((Path(temp) / "results").exists())

    def test_real_math_and_catalogue_workers_and_saved_report(self):
        with tempfile.TemporaryDirectory() as temp:
            result = engine.run_plan(
                engine.propose(QUERY + "; list available tools"), temp
            )
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(len(result["steps"]), 2)
            root = Path(result["output_dir"])
            document = json.loads((root / "step-01" / "report.json").read_text())
            self.assertIn("49.92809", json.dumps(document))
            self.assertEqual(json.loads((root / "result.json").read_text()), result)
            html = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn("Declared assumptions", html)
            self.assertIn("plan.json", html)
            self.assertFalse(
                any(Path(a["path"]).name == "worker.json" for a in result["artifacts"])
            )

    def test_cancelled_before_spawn(self):
        cancel = threading.Event()
        cancel.set()
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(engine.subprocess, "Popen") as spawn,
        ):
            result = engine.run_plan(engine.propose(QUERY), temp, cancel=cancel)
            self.assertEqual(result["status"], "cancelled")
            spawn.assert_not_called()

    def test_timeout_reaps_actual_child(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = Path(temp) / "slow.py"
            worker.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            with patch.object(engine, "_worker_path", return_value=worker):
                result = engine.run_plan(
                    engine.propose(QUERY), temp, timeout_seconds=0.1
                )
            self.assertEqual(result["steps"][0]["status"], "timed_out")
            self.assertLess(result["steps"][0]["seconds"], 20)

    def test_monitor_failure_still_terminates_worker(self):
        class BrokenCancel:
            def is_set(self):
                return False

            def wait(self, timeout):
                raise OSError("monitor failed")

        process = unittest.mock.Mock()
        process.poll.return_value = None
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(engine.subprocess, "Popen", return_value=process),
            patch.object(engine, "terminate") as stop,
        ):
            result = engine.run_plan(engine.propose(QUERY), temp, cancel=BrokenCancel())
            self.assertEqual(result["status"], "failed")
            self.assertIn("monitor failed", result["error"])
            stop.assert_called_once_with(process)

    def test_relative_and_log_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for bad in ("../outside", str(root / "absolute")):
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    engine._relative(root, bad)
            log = root / "log"
            log.write_bytes(b"x" * 1000)
            self.assertEqual(len(engine._read_log(log, 100)), 100)

    def test_changed_generated_settings_rejected_before_tool_import(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            root.mkdir()
            board = Path(temp) / "board.kicad_pcb"
            board.write_text("(kicad_pcb)", encoding="utf-8")
            spec = engine.ACTIONS["fanout-generator.preview"]
            plan = engine.propose(
                "preview connector fanout",
                {"board": str(board)},
                {"refs": "J1", "pattern": spec["fields"]["pattern"]["choices"][0]},
            )
            self.assertEqual(plan["status"], "ready", plan)
            compiled = engine._compile(plan["steps"][0], plan["context"], root)
            self.assertTrue(compiled["documents"])
            for name in compiled["documents"]:
                engine._write_new(root / name, {"tampered": True})
            engine._write_new(
                root / "worker.json", dict(plan=plan, index=0, output_dir=str(root))
            )
            process = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(engine._worker_path()),
                    str(root / "worker.json"),
                ],
                cwd=root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(process.returncode, 2)
            self.assertIn("Generated action inputs changed", process.stderr)

    def test_fast_exiting_large_log_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = Path(temp) / "verbose.py"
            worker.write_text("print('x' * 500)\n", encoding="utf-8")
            with (
                patch.object(engine, "_worker_path", return_value=worker),
                patch.object(engine, "MAX_LOG_BYTES", 100),
            ):
                result = engine.run_plan(engine.propose(QUERY), temp)
            self.assertEqual(result["steps"][0]["status"], "log_limit")
            self.assertEqual(result["status"], "completed_with_errors")


if __name__ == "__main__":
    unittest.main()
