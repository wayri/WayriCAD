"""LLM transport, all-plugin plan contracts and hostile evidence regressions."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from wayricad_runtime import assistant, assistant_ollama as ollama
from wayricad_runtime.assistant_actions import ACTIONS
from wayricad_runtime.tool_cli import COMMANDS


class OllamaTests(unittest.TestCase):
    def proposal(self, tasks, **options):
        with patch.object(ollama, '_chat', return_value=({'tasks': tasks},
                dict(provider='ollama', model='demo:latest', endpoint=ollama.DEFAULT_URL))):
            return ollama.propose('Run a registered check', model='demo:latest', **options)

    def test_every_plugin_and_action_can_be_proposed_without_execution(self):
        self.assertEqual(set(COMMANDS)-{'assistant'}, {v['tool'] for v in ACTIONS.values()})
        for identifier, spec in assistant._SPECS.items():
            with self.subTest(action=identifier):
                with patch.object(assistant, 'run_plan', side_effect=AssertionError('Must not execute')):
                    plan = self.proposal([dict(action=identifier, params={})])
                self.assertEqual(plan['steps'][0]['action'], identifier)
                self.assertEqual(plan['steps'][0]['effect'], spec['effect'])
                self.assertIn('interpretation', plan)
                self.assertEqual(plan['status'], 'needs_input' if spec['required'] else 'ready')
        schema = ollama.task_schema()
        registered = schema['properties']['tasks']['items']['properties']['action']['enum']
        self.assertEqual(set(registered), set(assistant._SPECS))

    def test_valid_numeric_plan_runs_existing_adapter(self):
        tasks = [dict(action='trace-impedance.cross-section', params=dict(
            topology='microstrip', width_mm=.2, height_mm=.1, er=4.2))]
        plan = self.proposal(tasks)
        self.assertEqual(plan['status'], 'ready')
        assistant.validate_plan(plan)
        with tempfile.TemporaryDirectory() as temp:
            result = assistant.run_plan(plan, Path(temp), timeout_seconds=30)
            self.assertEqual(result['status'], 'completed')
            self.assertTrue(result['artifacts'])

    def test_paths_unknown_actions_parameters_and_invalid_numbers_fail_closed(self):
        for task in [dict(action='shell', params={}),
                     dict(action='quick-pi.solve', params={'board': 'secret.kicad_pcb'}),
                     dict(action='harness-workbench.build', params={'documents': ['secret.json']}),
                     dict(action='quick-pi.solve', params={'apply': True}),
                     dict(action='quick-pi.solve', params={'current': float('nan')}),
                     dict(action='quick-pi.solve', params={'current': True}),
                     dict(action='quick-pi.solve', params={'net': '--apply'}),
                     dict(action='assistant.catalogue', params={}, command='rm')]:
            with self.subTest(task=task), self.assertRaises(ValueError):
                self.proposal([task])
        for tasks in ([], [{}]*9, {}, None):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                ollama.validate_tasks(tasks)

    def test_missing_inputs_answer_without_second_llm_call(self):
        plan = self.proposal([dict(action='trace-impedance.cross-section', params={'topology':'microstrip'})])
        with patch.object(ollama, '_chat', side_effect=AssertionError('No reinterpretation')):
            ready = ollama.propose('Run a registered check', answers=dict(width_mm=.2, height_mm=.1, er=4.2),
                model='demo:latest', previous=plan['interpretation'])
        self.assertEqual(ready['status'], 'ready')
        with self.assertRaises(ValueError):
            ollama.propose('Run a registered check', model='different', previous=plan['interpretation'])
        with self.assertRaises(ValueError):
            ollama.propose('Different request', model='demo:latest', previous=plan['interpretation'])

    def test_review_can_remove_inferred_optional_values(self):
        plan = self.proposal([dict(action='trace-impedance.cross-section', params=dict(
            topology='microstrip', width_mm=.2, height_mm=.1, er=4.2, copper_mm=.2))])
        with patch.object(ollama, '_chat', side_effect=AssertionError('No second model call')):
            reviewed = ollama.propose('Run a registered check', answers={'0.copper_mm':None},
                model='demo:latest', previous=plan['interpretation'])
        self.assertEqual(reviewed['status'],'ready')
        self.assertNotIn('copper_mm',reviewed['steps'][0]['params'])
        assistant.validate_plan(reviewed)

    def test_no_implicit_numeric_regex_inputs_in_llm_mode(self):
        with patch.object(ollama, '_chat', return_value=({'tasks': [dict(
                action='quick-pi.solve', params={})]}, {})):
            plan = ollama.propose('Use 5 V and 2 A but ask for all parameters', model='demo')
        self.assertNotIn('voltage', plan['steps'][0]['params'])
        self.assertNotIn('current', plan['steps'][0]['params'])
        plan = self.proposal([dict(action='quick-pi.solve', params={'current':None})])
        self.assertNotIn('current', plan['steps'][0]['params'])
        self.assertIn('0.current', [q['key'] for q in plan['questions']])

    def test_endpoint_never_leaves_loopback_or_uses_credentials(self):
        for url in ('https://127.0.0.1', 'http://example.com', 'http://127.0.0.2',
                    'http://localhost@evil.test', 'http://a:b@localhost',
                    'http://localhost/path', 'http://localhost?x=1', 'file:///tmp/model',
                    'http://localhost:0'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ollama.endpoint(url)
        self.assertEqual(ollama.endpoint('http://localhost:1234'), ('127.0.0.1',1234))
        self.assertEqual(ollama.endpoint('http://[::1]:1234'), ('::1',1234))

    def test_strict_json_duplicate_nonfinite_and_wrong_shapes(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', 'not json'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                ollama._strict_json(raw)
        for response in ({}, {'done':False}, {'done':True,'model':'wrong'},
                         {'done':True,'model':'demo','message':{'role':'assistant','content':'{}'},'done_reason':'length'}):
            with patch.object(ollama, '_request', side_effect=[{'capabilities':['completion']},response]), self.assertRaises(ValueError):
                ollama._chat('demo', [], {}, ollama.DEFAULT_URL, None, 5)

    def test_model_probe_and_complete_response_bind_request_and_disable_supported_thinking(self):
        response = {'done':True, 'model':'demo', 'message':{'role':'assistant','content':'{"tasks":[]}'}}
        with patch.object(ollama, '_request', side_effect=[
                {'capabilities':['completion','thinking'], 'model_info':{'demo.context_length':32768}}, response]) as request:
            value, provenance = ollama._chat('demo', [], {}, ollama.DEFAULT_URL, None, 5)
        self.assertEqual(value, {'tasks':[]})
        self.assertFalse(request.call_args_list[1].args[2]['think'])
        self.assertEqual(provenance['model'],'demo')
        self.assertEqual(len(provenance['request_sha256']),64)
        for info in ({'capabilities':['vision']}, {'capabilities':['completion'], 'model_info':{'demo.context_length':4096}},
                     {'capabilities':['completion'], 'remote_host':'https://ollama.com'},
                     {'capabilities':['completion'], 'remote_model':'cloud-model'}):
            with patch.object(ollama, '_request', return_value=info), self.assertRaises(ValueError):
                ollama._chat('demo', [], {}, ollama.DEFAULT_URL, None, 5)

    def test_context_budget_covers_full_prompt_schema_template_and_output(self):
        info = dict(capabilities=['completion'], model_info={'demo.context_length':16384})
        with patch.object(ollama, '_request', return_value=info) as request, self.assertRaises(ValueError):
            ollama._chat('demo', [dict(role='user', content='1,'*10000)], {}, ollama.DEFAULT_URL, None, 5)
        self.assertEqual(request.call_count,1)
        info['template'] = 'X'*16384
        with patch.object(ollama, '_request', return_value=info), self.assertRaises(ValueError):
            ollama._chat('demo', [], {}, ollama.DEFAULT_URL, None, 5)

    def evidence(self, root):
        path = root/'report.json'
        path.write_text(json.dumps(dict(status='unknown', impedance_ohm=49.928,
                                       assumptions=['zero-thickness approximation'])))
        return dict(status='completed', artifacts=[dict(path=str(path),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest())])

    def test_explanation_binds_hashes_and_preserves_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.evidence(root)
            response = dict(summary='An impedance estimate.', limitations=['Not protocol validation.'],
                            suggested_checks=['Refine material data.'], evidence_ids=['E1'])
            with patch.object(ollama, '_chat', return_value=(response, {})):
                explanation = ollama.explain(result, root, model='demo')
            self.assertEqual(explanation['host_status'], 'completed')
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(explanation['evidence'][0]['sha256'], result['artifacts'][0]['sha256'])
            (root/'report.json').write_text('{}')
            with patch.object(ollama, '_chat', side_effect=AssertionError('Stale evidence')), self.assertRaises(ValueError):
                ollama.explain(result, root, model='demo')

    def test_explanation_rejects_fabricated_citations_and_drift_during_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.evidence(root)
            response = dict(summary='Estimate', limitations=[], suggested_checks=[], evidence_ids=['E999'])
            with patch.object(ollama, '_chat', return_value=(response, {})), self.assertRaises(ValueError):
                ollama.explain(result, root, model='demo')
            response['evidence_ids'] = ['E1']
            def mutate(*args):
                (root/'report.json').write_text('{}')
                return response, {}
            with patch.object(ollama, '_chat', side_effect=mutate), self.assertRaises(ValueError):
                ollama.explain(result, root, model='demo')

    def test_explanation_refuses_traversal_empty_and_oversized_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.evidence(root)
            with self.assertRaises(ValueError):
                ollama.explain(result, root/'child', model='demo')
            with self.assertRaises(ValueError):
                ollama.explain(dict(artifacts=[]), root, model='demo')
            (root/'report.json').write_bytes(b' '*(ollama.MAX_EVIDENCE+1))
            with self.assertRaises(ValueError):
                ollama.explain(result, root, model='demo')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.mode = 'ok'
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if owner.mode == 'wait':
                    time.sleep(1)
                self.send_response(302 if owner.mode == 'redirect' else 200)
                self.send_header('Content-Length', str(ollama.MAX_RESPONSE+1) if owner.mode=='huge' else '13')
                self.end_headers()
                if owner.mode == 'body-wait':
                    time.sleep(1)
                try:
                    self.wfile.write(b'{"models":[]}')
                except OSError:
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_real_loopback_inventory(self):
        self.assertEqual(ollama.models(self.url), [])

    def test_no_redirect_and_bounded_response(self):
        for mode in ('redirect', 'huge'):
            self.mode = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                ollama.models(self.url)

    def test_timeout_and_cancellation_interrupt_transport(self):
        self.mode = 'wait'
        with self.assertRaises((RuntimeError, ValueError)):
            ollama._request(self.url, '/api/tags', timeout=.1)
        cancel = threading.Event()
        timer = threading.Timer(.1, cancel.set)
        timer.start()
        start = time.monotonic()
        with self.assertRaises(RuntimeError):
            ollama._request(self.url, '/api/tags', timeout=10, cancel=cancel)
        timer.join()
        self.assertLess(time.monotonic()-start, 2)

    def test_connection_close_stalled_body_respects_absolute_deadline(self):
        self.mode = 'body-wait'
        started = time.monotonic()
        with self.assertRaises((ValueError, RuntimeError)):
            ollama._request(self.url, '/api/tags', timeout=.1)
        self.assertLess(time.monotonic() - started, .8)


if __name__ == '__main__':
    unittest.main()
