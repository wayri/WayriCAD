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
    def test_circuit_context_resolves_unique_shared_net_and_case(self):
        from wayricad_runtime.assistant_context import CircuitInventory
        from wayricad_runtime.assistant import propose
        inventory = CircuitInventory(['/Power/VDD', 'GND'], {'J1': 'Input', 'U1': 'Regulator'},
                                     {'J1.1': {'/Power/VDD'}, 'U1.2': {'/Power/VDD'}})
        plan = propose('Quick PI voltage drop at 3.3 V from j1.1 to u1.2 with 250 mA',
                       inventory=inventory)
        params = plan['steps'][0]['params']
        self.assertEqual(plan['steps'][0]['action'], 'quick-pi.solve')
        self.assertEqual((params['source'], params['sink'], params['net'], params['current']),
                         ('J1.1', 'U1.2', '/Power/VDD', .25))
        self.assertIn('Saved endpoint pads share /Power/VDD.', plan['assumptions'])

    def test_unqualified_net_and_multiple_endpoint_pads_require_choices(self):
        from wayricad_runtime.assistant_context import CircuitInventory
        from wayricad_runtime.assistant import propose
        inventory = CircuitInventory(['/A/VDD', '/B/VDD'], {'J1': 'Input', 'U1': 'Load'},
                                     {'J1.1': {'/A/VDD'}, 'J1.2': {'/A/VDD'}, 'U1.1': {'/A/VDD'}})
        plan = propose('voltage drop net VDD from J1 to U1 at 3.3 V with .2 A', inventory=inventory)
        self.assertEqual(plan['status'], 'needs_input')
        fields = {row['key']: row for row in plan['questions']}
        self.assertEqual(fields['0.net']['choices'], ['/A/VDD', '/B/VDD'])
        self.assertEqual(fields['0.source']['choices'], ['J1.1', 'J1.2'])
        self.assertNotIn('net', plan['steps'][0]['params'])

    def test_distinct_analysis_modes_and_conversational_units(self):
        from wayricad_runtime.assistant import capabilities, propose, reply_answers
        cases = {'PI voltage drop on net VDD': 'quick-pi.solve',
                 'Quick PI AC impedance sweep': 'quick-pi.ac-ports',
                 'Quick PI transient load step': 'quick-pi.transient',
                 'Quick PI with Joule heating': 'quick-pi.electrothermal',
                 'Quick SI crosstalk between nets': 'signal-integrity.study',
                 'Thermal transient over time': 'quick-therm.transient',
                 'Thermal board heat map with U1 at .5 W and ambient 25 C': 'quick-therm.board-heat'}
        for request, action in cases.items():
            with self.subTest(request=request):
                self.assertEqual(propose(request)['steps'][0]['action'], action)
        plan = {'questions': [{'key': '0.current', 'kind': 'number', 'unit': 'A'}]}
        self.assertEqual(reply_answers(plan, 'Use 250 mA'), {'0.current': .25})
        self.assertEqual([provider['id'] for provider in capabilities()['providers']], ['local'])

    def test_pi_batch_resolves_each_rail_against_saved_pad_nets(self):
        from wayricad_runtime.assistant_context import CircuitInventory
        inventory = CircuitInventory(['/A/3V3', '/B/1V8'], {},
                                     {'J1.1': {'/A/3V3'}, 'U1.1': {'/A/3V3'},
                                      'J1.2': {'/B/1V8'}, 'U1.2': {'/B/1V8'}})
        query = ('Quick PI batch net 3V3 from j1.1 to u1.1 at 3.3 V with 250 mA, '
                 'net 1V8 from J1.2 to U1.2 at 1.8 V with 100 mA')
        plan = engine.propose(query, inventory=inventory)
        self.assertEqual(plan['steps'][0]['action'], 'quick-pi.batch-cases')
        self.assertIn('net "/A/3V3" from J1.1 to U1.1', plan['steps'][0]['params']['rails'])
        wrong = engine.propose(query.replace('to U1.2', 'to U1.1'), inventory=inventory)
        self.assertIn('does not match', next(row['error'] for row in wrong['questions'] if row['key']=='0.rails'))
        self.assertEqual(engine.propose('Quick PI batch study rails.json')['steps'][0]['action'], 'quick-pi.batch')
        prompt = engine.propose('Quick PI batch')
        self.assertIn('0.rails', engine.reply_answers(prompt, query))

    def test_pi_transient_requests_missing_physics_and_normalizes_units(self):
        query = ('PI transient source voltage 3.3 V, source resistance 50 mOhm, source inductance 100 nH, '
                 'initial current 200 mA, step current 1 A, step time 1 ms, path resistance 20 mOhm, '
                 'path inductance 10 nH, capacitance 100 \u00b5F, ESR 10 mOhm, duration 2 ms')
        partial = engine.propose(query)
        self.assertEqual(partial['steps'][0]['action'], 'quick-pi.load-step')
        self.assertEqual([row['key'] for row in partial['questions']], ['0.step_us'])
        values = engine.reply_answers(partial, 'Time step 1000 ns')
        self.assertAlmostEqual(values['0.step_us'], 1)
        plan = engine.propose(query, answers=values)
        self.assertEqual(plan['status'], 'ready')
        self.assertAlmostEqual(plan['steps'][0]['params']['initial_a'], .2)
        self.assertAlmostEqual(plan['steps'][0]['params']['cap_uf'], 100.)
        self.assertEqual(engine.propose('Quick PI transient study example.json')['steps'][0]['action'],
                         'quick-pi.transient')

    def test_analytics_and_board_heat_intents(self):
        for query, action, params in (
            ('Give me the number of 10u capacitors','bom-studio.count-value',{'kind':'C','value':'10u'}),
            ('Give me layer wise total copper area','bom-studio.copper',{}),
            ('Solve board heat map at 25 C with C1=0.5 W','quick-therm.board-heat',
             {'ambient':25.,'powers':['C1=0.5']}),
        ):
            with self.subTest(query=query):
                plan = engine.propose(query)
                self.assertEqual(plan['status'],'needs_input')
                self.assertEqual(plan['steps'][0]['action'],action)
                self.assertEqual(plan['steps'][0]['params'],params)

    def test_common_intents_and_clarifications(self):
        examples = {
            "simulate power integrity": "quick-pi.solve",
            "check signal integrity": "signal-integrity.screen",
            "analyze board temperature": "quick-therm.board-heat",
            "screen component temperatures": "quick-therm.analyze",
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

    def test_guard_net_is_explicit_and_never_inferred_from_selected_signal(self):
        plan=engine.propose('guard via stitching',{'selected_nets':['CLK','DATA']})
        self.assertEqual(plan['steps'][0]['action'],'via-stitching.guard')
        self.assertEqual(plan['steps'][0]['params']['signal_nets'],['CLK','DATA'])
        self.assertNotIn('guard_net',plan['steps'][0]['params'])
        self.assertIn('0.guard_net',[q['key'] for q in plan['questions']])
        plan=engine.propose('via fence along net CLK with guard net GND pitch 2 mm offset 1 mm')
        self.assertEqual(plan['steps'][0]['params']['guard_net'],'GND')
        self.assertEqual(plan['steps'][0]['params']['signal_nets'],['CLK'])
        self.assertEqual(plan['steps'][0]['params']['spacing'],2.)
        self.assertEqual(plan['steps'][0]['params']['offset'],1.)

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
