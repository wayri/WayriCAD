"""Native window state and local report-boundary regressions."""
from pathlib import Path
import tempfile
import threading
import time
import unittest

try:
    import wx
    from suite_assistant_plugin.gui import AssistantFrame, EXAMPLES, report_path
except ImportError:
    wx = None


class Engine:
    def __init__(self):
        self.answers = []
        self.runs = 0

    def propose(self, query, context, answers):
        self.answers.append(dict(answers))
        if '0.net' not in answers:
            return {'status': 'needs_input', 'query': query, 'steps': [{'action': 'return', 'title': 'Return path'}],
                    'questions': [{'key': '0.net', 'label': 'Net', 'choices': ['GND', '+3V3']}]}
        return {'status': 'ready', 'query': query, 'steps': [{'action': 'return', 'title': 'Return path', 'params': answers}]}

    def run_plan(self, plan, output_root, *, cancel, progress):
        self.runs += 1
        progress('Inspecting')
        path = Path(output_root) / 'result.html'
        path.write_text('<p>Complete</p>', encoding='utf-8')
        return {'status': 'complete', 'summary': 'Return path checked.', 'output_dir': str(output_root),
                'artifacts': [{'path': str(path), 'label': 'Report', 'kind': 'html'}]}


@unittest.skipUnless(wx is not None, 'KiCad native wxPython is required')
class AssistantWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = Engine()
        self.frame = AssistantFrame(engine=self.engine, output_root=self.root)
        self.frame.Show()

    def tearDown(self):
        if not self.frame.closed:
            self.frame._close(None)
        wx.Yield()
        self.temp.cleanup()

    def settle(self):
        deadline = time.monotonic() + 3
        while self.frame.busy and time.monotonic() < deadline:
            wx.Yield()
            time.sleep(.01)
        wx.Yield()
        self.assertFalse(self.frame.busy)

    def test_missing_input_form_then_automatic_execution(self):
        self.frame.query.ChangeValue('check return path')
        self.frame._ask(); self.settle()
        self.assertEqual(self.engine.runs, 0)
        self.assertTrue(self.frame.questions.IsShown())
        self.frame.question_controls['0.net'].SetValue('+3V3')
        self.frame._answer(None); self.settle()
        self.assertEqual(self.engine.answers[-1], {'0.net': '+3V3'})
        self.assertEqual(self.engine.runs, 1)
        self.assertEqual(self.frame.report_list.GetCount(), 1)
        self.assertIn('Return path checked', self.frame.results.GetValue())

    def test_auto_run_off_leaves_reviewable_plan(self):
        self.frame.auto.SetValue(False)
        self.frame.query.ChangeValue('check return path')
        self.frame._ask(answers={'0.net': 'GND'}); self.settle()
        self.assertTrue(self.frame.run.IsEnabled())
        self.assertEqual(self.engine.runs, 0)
        self.frame._run(); self.settle()
        self.assertEqual(self.engine.runs, 1)

    def test_visual_selection_invalidates_old_plan(self):
        self.frame.plan = {'status': 'ready'}
        self.frame.run.Enable()
        self.frame.preview.net_targets = [{'net': 'GND', 'start': (0, 0), 'end': (2, 1), 'radius': .1},
                                          {'net': '+3V3', 'start': (3, 0), 'end': (5, 1), 'radius': .1}]
        self.frame._select_net('GND', (1, 1))
        self.assertEqual(self.frame.context['selected_nets'], ['GND'])
        self.assertEqual(self.frame.preview.lines, [(0, 0, 2, 1)])
        self.frame.tabs.SetSelection(2)
        self.frame.preview.Refresh(); self.frame.preview.Update(); wx.Yield()
        self.assertFalse(self.frame.run.IsEnabled())

    def test_closed_window_discards_queued_callbacks(self):
        calls = []
        self.frame._deliver(calls.append, 'late')
        self.frame._close(None)
        wx.Yield()
        self.assertEqual(calls, [])
        self.assertTrue(self.frame.cancel_event.is_set())

    def test_report_file_boundary_and_extensions(self):
        inside = self.root / 'report.html'; inside.write_text('ok', encoding='utf-8')
        self.assertEqual(report_path({'path': 'report.html'}, self.root), inside.resolve())
        outside = self.root.parent / 'private.html'
        with self.assertRaises(ValueError):
            report_path({'path': str(outside)}, self.root)
        executable = self.root / 'run.py'; executable.write_text('pass', encoding='utf-8')
        with self.assertRaises(ValueError):
            report_path({'path': str(executable)}, self.root)

    def test_board_change_drops_selected_context_and_preview(self):
        board = self.root / 'example.kicad_pcb'; board.touch()
        project = board.with_suffix('.kicad_pro'); project.touch()
        self.frame.context = {'selected_nets': ['old'], 'board': 'old'}
        self.frame.preview.net_targets = [{'net': 'old'}]
        self.frame.set_board(board)
        self.assertEqual(self.frame.context, {'board': str(board.resolve()), 'project': str(project.resolve())})
        self.assertEqual(self.frame.preview.net_targets, [])

    def test_multiple_clicked_nets_are_explicit_and_can_be_cleared(self):
        self.frame.add_nets.SetValue(True)
        self.frame._select_net('GND', (0, 0))
        self.frame._select_net('+3V3', (0, 0))
        self.frame._select_net('GND', (0, 0))
        self.assertEqual(self.frame.context['selected_nets'], ['GND', '+3V3'])
        self.frame._clear_nets()
        self.assertNotIn('selected_nets', self.frame.context)

    def test_structured_numerical_result_is_shown_without_opening_browser(self):
        path = self.root / 'report.json'
        path.write_text('{"result":{"status":"ESTIMATE","single_ended_z0_ohm":49.928}}', encoding='utf-8')
        self.frame._show_result({'status': 'completed', 'summary': 'Complete', 'output_dir': str(self.root),
                                 'artifacts': [{'path': str(path), 'label': 'report.json'}]})
        self.assertIn('49.928', self.frame.results.GetValue())
        self.assertIn('ESTIMATE', self.frame.results.GetValue())

    def test_failed_preview_load_returns_to_actionable_state(self):
        self.frame._set_busy(True)
        self.frame._show_board(self.frame._generation, None, None)
        self.assertFalse(self.frame.busy)
        self.assertIsNone(self.frame.loaded_board)
        self.assertTrue(self.frame.ask.IsEnabled())

    def test_boolean_answers_offer_true_and_false(self):
        self.frame.query.ChangeValue('Check')
        self.frame._show_plan({'status': 'needs_input', 'questions': [
            {'key': '0.enabled', 'label': 'Enable option', 'kind': 'boolean'}]})
        control = self.frame.question_controls['0.enabled']
        self.assertEqual(control.GetItems(), ['true', 'false'])
        control.SetValue('false')
        self.frame._answer(None); self.settle()
        self.assertEqual(self.engine.answers[-1]['0.enabled'], 'false')

    def test_examples_resolve_actual_registered_actions(self):
        from wayricad_runtime.assistant import propose
        for query in EXAMPLES:
            with self.subTest(query=query):
                plan = propose(query, {}, {})
                self.assertIn(plan['status'], {'ready', 'needs_input'})
                self.assertTrue(plan['steps'])

    def test_default_results_location_is_discoverable_and_persistent(self):
        other = AssistantFrame(engine=self.engine)
        try:
            self.assertEqual(other.output_root, Path(wx.StandardPaths.Get().GetDocumentsDir()) /
                             'WayriCAD' / 'Assistant' / 'results')
            self.assertTrue(other.open_output.IsShown())
            self.assertIn(str(other.output_root), other.choose_output.GetToolTipText())
        finally:
            other._close(None)

    def test_run_root_cannot_escape_output_folder(self):
        self.frame._show_result({'status': 'completed', 'output_dir': str(self.root.parent),
                                 'artifacts': [{'path': str(self.root.parent / 'report.html')}]})
        self.assertEqual(self.frame.artifacts, [])
        self.assertIn('outside', self.frame.results.GetValue())

    def test_input_errors_and_previous_values_remain_visible(self):
        self.frame.answers = {'0.width_mm': '-1'}
        self.frame._show_plan({'status': 'needs_input', 'error': 'Review invalid geometry.',
                              'questions': [{'key': '0.width_mm', 'label': 'Width', 'kind': 'number',
                                             'error': 'Width must be positive.'}]})
        self.assertIn('Review invalid geometry', self.frame.plan_text.GetValue())
        control = self.frame.question_controls['0.width_mm']
        self.assertEqual(control.GetValue(), '-1')
        self.assertIn('Width must be positive', control.GetToolTipText())
        self.assertTrue(any(isinstance(child, wx.StaticText) and child.GetLabel() == 'Width must be positive.'
                            for child in self.frame.questions.GetChildren()))

    def test_close_keeps_broker_alive_until_cancellation_is_recorded(self):
        started = threading.Event()
        recorded = self.root / 'cancelled.txt'
        class BlockingEngine:
            def run_plan(inner, plan, output_root, *, cancel, progress):
                started.set()
                if not cancel.wait(2):
                    raise RuntimeError('Cancellation was not forwarded.')
                recorded.write_text('cancelled', encoding='utf-8')
                return {'status': 'cancelled', 'summary': 'Cancelled', 'artifacts': []}
        self.frame.engine = BlockingEngine()
        self.frame.plan = {'status': 'ready'}
        self.frame._run()
        self.assertTrue(started.wait(1))
        self.assertFalse(self.frame.run_thread.daemon)
        self.frame._close(None)
        self.frame.run_thread.join(2)
        self.assertFalse(self.frame.run_thread.is_alive())
        self.assertEqual(recorded.read_text(encoding='utf-8'), 'cancelled')
        wx.Yield()  # No result callback may touch the destroyed window.

    def test_small_window_keeps_resizable_work_area(self):
        self.frame.SetSize((760, 600)); self.frame.Layout(); wx.Yield()
        self.assertGreater(self.frame.tabs.GetSize().height, 100)
        self.assertEqual(self.frame.tabs.GetPageCount(), 3)


if __name__ == '__main__':
    unittest.main()
