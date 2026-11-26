"""Contract and hostile-input tests for the Assistant's fixed CLI adapters."""
import argparse
import importlib
import json
import tempfile
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
            elif key == 'rails': values[key] = ('net 3V3 from J1.1 to U1.1 at 3.3 V with 250 mA, '
                                                   'net 1V8 from J1.2 to U1.2 at 1.8 V with 100 mA')
            elif key == 'source_unit': values[key] = 'J1.1+J1.2'
            elif key == 'load_units': values[key] = 'U1.1+U1.2 @ 250 mA | U2.1 @ 100 mA'
            elif key == 'powers': values[key] = ['U1=0.5']
            elif kind == 'path': values[key] = str(self.root / 'spec.json')
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

    def test_conversational_pi_creates_native_configurations(self):
        from quick_pi_plugin.batch import validate_study
        from quick_pi_plugin.transient import _request
        batch = self.compile('quick-pi.batch-cases')
        study = batch['documents']['settings.json']
        validate_study(study)
        self.assertIn('--batch', batch['arguments'])
        self.assertEqual([row['electrical']['sink_current'] for row in study['cases']], [.25, .1])
        transient = self.compile('quick-pi.load-step')
        self.assertIn('--transient', transient['arguments'])
        line = _request(transient['documents']['settings.json'])
        self.assertAlmostEqual(line['loads'][0]['capacitance_F'], 1e-6)
        self.assertAlmostEqual(line['step_s'], 1e-6)
        self.assertFalse(self.output.exists())

    def test_study_console_bounds_an_oversized_json_echo(self):
        from io import StringIO
        from wayricad_runtime.assistant_worker import _StudyConsole
        output = StringIO()
        stream = _StudyConsole(output)
        stream.write('x' * (9 * 1024 * 1024))
        stream.write('A native diagnostic')
        self.assertIn('report.json', output.getvalue())
        self.assertIn('A native diagnostic', output.getvalue())
        self.assertLess(len(output.getvalue()), 100)

    def test_dc_with_returns_keeps_the_solve_and_reviews_return_geometry(self):
        values = dict(self.sample('quick-pi.solve'), return_nets=['GND'], mesh_backend='vtk', temperature=30)
        result = self.compile('quick-pi.solve', values)
        self.assertIn('--batch', result['arguments'])
        self.assertNotIn('--return-path', result['arguments'])
        case = result['documents']['settings.json']['cases'][0]
        self.assertEqual(case['electrical']['sink_current'], values['current'])
        self.assertEqual(case['electrical']['mesh_backend'], 'vtk')
        self.assertEqual(case['electrical']['options']['temperature_c'], 30)
        self.assertEqual(case['return_path']['return_nets'], ['GND'])

    def test_study_uses_a_distinct_html_stem_when_the_native_cli_supports_it(self):
        for action in ('quick-pi.ac', 'quick-pi.transient', 'quick-pi.solid', 'quick-therm.transient', 'signal-integrity.study'):
            with self.subTest(action=action):
                self.assertEqual(self.compile(action)['outputs'], ['report.json', 'study.html'])
        for action in ('quick-pi.ac-ports', 'quick-pi.plane-ports'):
            with self.subTest(action=action):
                self.assertEqual(self.compile(action)['outputs'], ['report.json'])

    def test_board_heat_builds_only_explicit_source_watts(self):
        values = dict(board=self.context['board'],ambient=25,powers=['C1=0.5','C2=0'])
        result = self.compile('quick-therm.board-heat',values)
        config = result['documents']['settings.json']
        self.assertEqual(config['manual_values'],{'C1':{'power_w':.5},'C2':{'power_w':0.}})
        self.assertTrue(config['board_power_only'])
        self.assertIn('--no-solver-install',result['arguments'])
        for bad in (['C1=-1'],['C1=0'],['C1=1','C1=2'],['C1=NaN']):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                self.compile('quick-therm.board-heat',dict(values,powers=bad))

    def test_count_value_normalizes_capacitance_and_returns_refs(self):
        from bom_studio_plugin.bomstudio import cli
        fixture = Path(cli.__file__).resolve().parents[1] / 'examples' / 'BOM_Demo.kicad_pro'
        for nominal in ('10u','10uF','10000nF','10 \u00b5F'):
            with self.subTest(nominal=nominal),patch.object(cli,'emit') as emit:
                self.assertEqual(cli.main(['count-value',str(fixture),'--source-only',
                                          '--kind=C','--value='+nominal]),0)
                report = emit.call_args.args[0]
                self.assertEqual(report['count'],1)
                self.assertEqual(report['references'],['C3'])

    def test_emerge_example_builds_a_revision_bound_worker_request(self):
        from quick_emerge_plugin import __main__ as cli, backend
        board = Path(cli.__file__).resolve().parent/'tests'/'fixtures'/'region_coupon.kicad_pcb'
        with (tempfile.TemporaryDirectory() as temp, patch.object(backend,'run_request') as run,
              patch('quick_emerge_plugin.solver_probe._local_mkl_path',return_value='mkl_rt.dll'),
              patch('quick_emerge_plugin.reporting.export_html') as report):
            result = Path(temp)/'result.json'
            html = Path(temp)/'report.html'
            self.assertEqual(cli.main(['--board',str(board),'--run-research-example','rezaeipour-2021-dual-feed-patch',
                                       '--result-file',str(result),'--report-file',str(html),
                                       '--research-solver','PARDISO','--research-threads','4']),0)
            request = run.call_args.args[0]
            self.assertEqual(report.call_args.args, (html.resolve(), run.return_value))
            record = json.loads(request.read_text(encoding='utf-8'))
            self.assertEqual(record['source'],backend.source_identity(board))
            self.assertEqual(record['config_sha256'],backend.config_digest(record['config']))
            self.assertEqual(record['config']['solver'], 'PARDISO')
            self.assertEqual(record['config']['advanced']['solver_threads'], 4)

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
        self.assertFalse(doc.get('use_netclass_rules', False))
        params = dict(self.sample('fanout-generator.preview'), netclass='Default')
        selected = self.compile('fanout-generator.preview', params)['documents']['settings.json']
        self.assertTrue(selected['use_netclass_rules'])
        self.assertEqual(selected['netclass_filter'], 'Default')
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
                 'quick-pi.ac-ports': 'quick_pi_plugin.cli',
                 'quick-pi.series': 'quick_pi_plugin.cli',
                 'quick-pi.batch': 'quick_pi_plugin.cli',
                 'quick-pi.batch-cases': 'quick_pi_plugin.cli',
                 'quick-pi.load-step': 'quick_pi_plugin.cli',
                 'quick-pi.power-tree': 'quick_pi_plugin.cli',
                 'quick-pi.infer-series': 'quick_pi_plugin.cli',
                 'quick-therm.analyze': 'quick_therm_plugin.cli',
                 'quick-therm.board-heat': 'quick_therm_plugin.cli',
                 'quick-therm.transient': 'quick_therm_plugin.cli',
                 'quick-therm.solid': 'quick_therm_plugin.cli',
                 'quick-emerge.run-example': 'quick_emerge_plugin.__main__',
                 'signal-integrity.screen': 'signal_integrity_advisor_plugin.cli',
                 'signal-integrity.study': 'signal_integrity_advisor_plugin.cli',
                 'bom-studio.count-value': 'bom_studio_plugin.bomstudio.cli',
                 'bom-studio.copper': 'bom_studio_plugin.bomstudio.cli',
                 'trace-impedance.path': 'trace_impedance_plugin.cli',
                 'trace-impedance.cross-section': 'trace_impedance_plugin.cli',
                 'fanout-generator.preview': 'wayricad_runtime.cli',
                 'via-stitching.preview': 'wayricad_runtime.cli',
                 'trace-refiner.preview': 'trace_refiner_plugin.cli',
                 'component-arranger.preview': 'component_arranger_plugin.cli',
                 'silkscreen-label-placer.preview': 'silkscreen_label_plugin.cli',
                 'portable-web-export.build': 'portable_web_export_plugin.cli',
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
