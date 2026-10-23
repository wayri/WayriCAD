"""Contract and hostile-input tests for the Assistant's fixed CLI adapters."""
import argparse
import importlib
import json
from pathlib import Path
import uuid
import unittest
from unittest.mock import patch

from wayricad_runtime.assistant_actions import ACTIONS, compile_action
from wayricad_runtime.tool_cli import COMMANDS


class Parsed(BaseException):
    pass


class AssistantActionsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / '.validation' / ('assistant-test-' + uuid.uuid4().hex)
        self.output = self.root / 'private-run'
        self.context = dict(board=str(self.root / 'Example.kicad_pcb'),
                            project=str(self.root / 'Example.kicad_pro'))

    def sample(self, identifier):
        spec = ACTIONS[identifier]
        values = {}
        for key in spec['required']:
            field = spec['fields'][key]
            kind = field['kind']
            if key in self.context: values[key] = self.context[key]
            elif kind == 'choice': values[key] = field['choices'][0]
            elif kind == 'number': values[key] = max(1, field.get('minimum', 1))
            elif kind == 'integer': values[key] = 2
            elif kind == 'paths': values[key] = [str(self.root / 'pins.csv')]
            elif kind == 'list': values[key] = ['U1', 'U2'] if key == 'refs' else ['GND', '+3V3']
            else: values[key] = {'net': '+3V3', 'source': 'J1.1', 'sink': 'U1.1',
                                'start': 'J1.1', 'end': 'U1.1', 'refs': 'U1',
                                'pattern': '*', 'replacement': 'X*'}.get(key, 'Field')
        return values

    def compile(self, identifier, params=None):
        return compile_action(identifier, self.sample(identifier) if params is None else params,
                              self.context, self.output)

    def test_every_tool_has_honest_help_and_substantive_action(self):
        tools = set(COMMANDS) - {'assistant'}
        self.assertEqual(tools, {s['tool'] for s in ACTIONS.values()})
        for tool in tools:
            with self.subTest(tool=tool):
                help_action = ACTIONS[tool + '.help']
                self.assertEqual(help_action['effect'], 'help')
                self.assertEqual(self.compile(tool + '.help')['arguments'], ['--help'])
                self.assertTrue(any(s['tool'] == tool and s['effect'] != 'help' for s in ACTIONS.values()))
        self.assertNotIn('assistant.help', ACTIONS)

    def test_all_catalog_actions_compile_without_writes(self):
        json.dumps(ACTIONS, allow_nan=False)
        for identifier in ACTIONS:
            with self.subTest(action=identifier):
                result = self.compile(identifier)
                self.assertIn(result['tool'], COMMANDS)
                self.assertTrue(all(isinstance(arg, str) for arg in result['arguments']))
                for output in [*result['outputs'], *result['documents']]:
                    self.assertFalse(Path(output).is_absolute())
                    self.assertNotIn('..', Path(output).parts)
                json.dumps(result, allow_nan=False)
                self.assertFalse(self.output.exists())

    def test_no_source_mutation_switch_or_command(self):
        forbidden = {'--apply', '--yes', '--install', '--save-settings', '--init-rules',
                     '--output-board', '--repair', 'apply', 'repair', 'restore'}
        for identifier in ACTIONS:
            with self.subTest(action=identifier):
                result = self.compile(identifier)
                self.assertFalse(set(result['arguments']) & forbidden)
                self.assertFalse(any(p.endswith('.kicad_pcb') for p in result['outputs']))

    def test_unknown_parameters_rejected_for_every_action(self):
        for identifier in ACTIONS:
            with self.subTest(action=identifier):
                with self.assertRaises(ValueError): self.compile(identifier, dict(self.sample(identifier), apply=True))

    def test_numeric_and_boolean_are_strict(self):
        base = self.sample('quick-pi.solve')
        for bad in [True, '1', float('nan'), float('inf'), -1, 0, 10 ** 500]:
            with self.subTest(value=bad):
                with self.assertRaises(ValueError): self.compile('quick-pi.solve', dict(base, current=bad))
        with self.assertRaises(ValueError):
            self.compile('trace-refiner.preview', dict(board=self.context['board'], center_contacts='yes'))

    def test_hostile_text_cannot_become_options(self):
        for bad in ['--output=outside.json', '-x', 'GND\n--apply', 'GND\x00X']:
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    self.compile('quick-pi.solve', dict(self.sample('quick-pi.solve'), net=bad))
        # Shell metacharacters remain one data token; execution never uses shell=True.
        result = self.compile('quick-pi.solve', dict(self.sample('quick-pi.solve'), net='A; echo X $(whoami)'))
        self.assertIn('--net=A; echo X $(whoami)', result['arguments'])
        self.assertNotIn('echo', result['arguments'])

    def test_missing_physics_raises_instead_of_guessing(self):
        with self.assertRaisesRegex(ValueError, 'voltage'):
            self.compile('quick-pi.solve', dict(net='+3V3', source='J1.1', sink='U1.1', current=1))
        with self.assertRaisesRegex(ValueError, 'gap_mm'):
            self.compile('trace-impedance.cross-section', dict(topology='cpw', width_mm=.2, height_mm=.1, er=4))
        with self.assertRaisesRegex(ValueError, 'theta_ja_field'):
            self.compile('quick-therm.analyze', dict(power_field='P', ambient=25))

    def test_context_only_fills_known_inputs_and_no_output_alias(self):
        result = self.compile('trace-impedance.inspect', {})
        self.assertEqual(result['input_files'], [self.context['board']])
        with self.assertRaises(ValueError):
            self.compile('trace-impedance.inspect', dict(board=str(self.output / 'report.json')))
        with self.assertRaises(ValueError): self.compile('trace-impedance.inspect', dict(board='-'))

    def test_documents_are_constrained_and_unknown_config_refused(self):
        result = self.compile('fanout-generator.preview')
        doc = result['documents']['settings.json']
        self.assertEqual(doc['scope'], 'Reference wildcard')
        self.assertTrue(doc['use_netclass_rules'])
        self.assertNotIn('output', doc)
        with self.assertRaises(ValueError): self.compile('quick-therm.analyze', dict(config='untrusted.json'))
        audit = self.compile('manufacturing-readiness.audit')['documents']['request.json']
        self.assertTrue(audit['metrics']['routed_edge_unknown'])

    def test_generated_control_requests_run_existing_pure_backends(self):
        from extract_pins_plugin.automation import execute
        cases = {
            'bulk-label-editor.preview': dict(values=['A1', 'B1'], pattern='A*', replacement='C*'),
            'protocol-constraints.compose': dict(nets=['USB_D+', 'USB_D-', 'GND']),
            'manufacturing-readiness.audit': dict(minimum_track_mm=.2, minimum_clearance_mm=.2,
                minimum_drill_mm=.3, minimum_annular_ring_mm=.15,
                maximum_via_aspect_ratio=5, copper_layers=4),
            'heater-designer.analyze': dict(width_mm=80, height_mm=50, trace_width_mm=.5,
                spacing_mm=.5, copper_um=35, voltage_v=12),
            'planar-magnetics.analyze': dict(outer_width_mm=35, outer_height_mm=35,
                turns=8, trace_width_mm=.5, spacing_mm=.25, copper_um=35,
                layers=2, frequency_khz=100, current_a=.5, voltage_v=5),
        }
        from wayricad_runtime.tool_cli import CONTROL_METHODS
        for identifier, params in cases.items():
            with self.subTest(action=identifier):
                compiled = self.compile(identifier, params)
                response = execute(dict(jsonrpc='2.0', id=1,
                    method=CONTROL_METHODS[compiled['tool']],
                    params=compiled['documents']['request.json']))
                self.assertNotIn('error', response, response)
                json.dumps(response, allow_nan=False)

    def test_representative_actual_cli_parsers_accept_argv(self):
        # Capture the real parser's completed namespace, before a solver/native
        # import runs. This exercises current CLI flags rather than a mock schema.
        real_parse = argparse.ArgumentParser.parse_args
        captured = []
        def parse(parser, *args, **kwargs):
            namespace = real_parse(parser, *args, **kwargs)
            captured.append(namespace)
            raise Parsed()
        cases = {'quick-pi.solve': 'quick_pi_plugin.cli',
                 'quick-therm.analyze': 'quick_therm_plugin.cli',
                 'signal-integrity.screen': 'signal_integrity_advisor_plugin.cli',
                 'trace-impedance.path': 'trace_impedance_plugin.cli',
                 'trace-impedance.cross-section': 'trace_impedance_plugin.cli',
                 'fanout-generator.preview': 'wayricad_runtime.cli',
                 'via-stitching.preview': 'wayricad_runtime.cli',
                 'trace-refiner.preview': 'trace_refiner_plugin.cli',
                 'component-arranger.preview': 'component_arranger_plugin.cli',
                 'silkscreen-label-placer.preview': 'silkscreen_label_plugin.cli',
                 'project-fusion.detect': 'project_fusion_plugin.cli',
                 'heater-designer.analyze': 'wayricad_runtime.control_cli'}
        for identifier, module_name in cases.items():
            with self.subTest(action=identifier):
                result = self.compile(identifier)
                prefix = list(COMMANDS[result['tool']][1])
                module = importlib.import_module(module_name)
                captured.clear()
                with patch.object(argparse.ArgumentParser, 'parse_args', parse):
                    with self.assertRaises(Parsed): module.main(prefix + result['arguments'])
                self.assertEqual(len(captured), 1)


if __name__ == '__main__':
    unittest.main()
