"""Controller policy tests without creating or operating native windows."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
try:
    from quick_emerge_plugin.ui import QuickEMergeFrame
    from quick_emerge_plugin.report_preview import ReportPreview
except ImportError:
    QuickEMergeFrame = ReportPreview = None


@unittest.skipIf(QuickEMergeFrame is None, 'Desktop modules unavailable')
class WorkbenchPolicyTests(unittest.TestCase):
    def frame(self):
        solver = SimpleNamespace(value='SUPERLU', SetToolTip=Mock())
        solver.SetStringSelection = lambda value: setattr(solver, 'value', value)
        frame = SimpleNamespace(closed=False, _solver_probe_generation=2,
            solver_probe_busy=True, solver_probe_python=None, solver_environment={},
            _solver_explicit=False, result=None, solver=solver,
            session=SimpleNamespace(review={'reviewed':True}, preview=Mock()),
            region_plan={'source':'reviewed crop'}, running=False,
            region_busy=False, dependency_busy=False, running_state=Mock(), SetStatusText=Mock())
        frame.config = lambda: {'solver':solver.value}
        return frame

    def response(self):
        return {'schema':1,'available':['SUPERLU','PARDISO'],'preferred':'PARDISO',
                'diagnostics':{'PARDISO':{'library':'C:/Runtime/Library/bin/mkl_rt.3.dll'}}}

    def test_stale_probe_does_not_replace_current_choice(self):
        frame=self.frame()
        QuickEMergeFrame._solver_probe_done(frame,1,'old-python',self.response(),None)
        self.assertEqual(frame.solver.value,'SUPERLU')
        self.assertIsNone(frame.solver_probe_python)

    def test_verified_preference_rebinds_review_without_discarding_geometry(self):
        frame=self.frame()
        QuickEMergeFrame._solver_probe_done(frame,2,'current-python',self.response(),None)
        self.assertEqual(frame.solver.value,'PARDISO')
        frame.session.preview.assert_called_once_with({'solver':'PARDISO'},region=frame.region_plan)
        self.assertEqual(frame.solver_environment,{'EMERGE_PARDISO_PATH':'C:/Runtime/Library/bin/mkl_rt.3.dll'})

    def test_explicit_choice_and_existing_result_are_preserved(self):
        for explicit,result in [(True,None),(False,{'recorded':'result'})]:
            with self.subTest(explicit=explicit):
                frame=self.frame();frame._solver_explicit=explicit;frame.result=result
                QuickEMergeFrame._solver_probe_done(frame,2,'current-python',self.response(),None)
                self.assertEqual(frame.solver.value,'SUPERLU')
                frame.session.preview.assert_not_called()
                self.assertIs(frame.result,result)

    def test_changed_source_invalidates_review_instead_of_reusing_it(self):
        frame=self.frame();frame.session.preview.side_effect=ValueError('source changed')
        QuickEMergeFrame._solver_probe_done(frame,2,'current-python',self.response(),None)
        self.assertIsNone(frame.session.review)

    def test_background_dependency_setup_keeps_geometry_editable(self):
        frame=self.frame();frame.dependency_busy=True
        for name in ['settings','preview_button','run_button','cancel_button','dependencies_button','rollback_button']:
            setattr(frame,name,Mock())
        QuickEMergeFrame.running_state(frame,False)
        frame.settings.Enable.assert_called_once_with(True)
        frame.preview_button.Enable.assert_called_once_with(True)
        frame.run_button.Enable.assert_called_once_with(False)
        frame.cancel_button.SetLabel.assert_called_once_with('Cancel setup')

    def test_results_backend_is_readable_without_dumping_metadata(self):
        table=Mock();table.InsertItem.return_value=0
        frame=SimpleNamespace(result={'backend':{'backend':'EMerge','version':'3.0.0b9','adapter_revision':'hash'}},
            result_table=table,result_summary=Mock(),render_backend='VTK')
        QuickEMergeFrame.refresh_results(frame)
        table.SetItem.assert_any_call(0,1,'EMerge 3.0.0b9')

    def test_new_run_preserves_geometry_and_discards_old_report(self):
        frame=SimpleNamespace(session=SimpleNamespace(start=Mock(),run_dir='run'),
            config=lambda:{'solver':'PARDISO'},python=SimpleNamespace(GetPath=lambda:'runtime'),
            output=SimpleNamespace(GetPath=lambda:'output'),solver_environment={},solver_probe_python='runtime',
            result={'old':True},reset_report_preview=Mock(),clear_inspection=Mock(),
            viewports={name:Mock() for name in ('3D setup','PCB enclosure','S-parameters','3D fields')},
            running_state=Mock(),log=Mock(),details=Mock(),SetStatusText=Mock(),timer=Mock(),message=Mock())
        QuickEMergeFrame.run(frame,None)
        self.assertIsNone(frame.result)
        frame.reset_report_preview.assert_called_once_with('Simulation running. Generate a report when it completes.')
        for name in ('3D setup','PCB enclosure'):frame.viewports[name].clear.assert_not_called()
        for name in ('S-parameters','3D fields'):frame.viewports[name].clear.assert_called_once()
        frame.timer.Start.assert_called_once_with(500)
        frame.message.assert_not_called()

    def test_report_reset_clears_old_document_and_load_state(self):
        frame=SimpleNamespace(report_preview_ready=True,report_status=Mock(),report_preview=Mock())
        QuickEMergeFrame.reset_report_preview(frame,'Simulation running')
        self.assertFalse(frame.report_preview_ready)
        frame.report_status.SetLabel.assert_called_once_with('Simulation running')
        frame.report_preview.clear.assert_called_once_with('Simulation running')

    def test_report_placeholder_escapes_message_and_ignores_pending_load(self):
        frame=SimpleNamespace(signature='old',pending=True,browser=Mock())
        ReportPreview.clear(frame,'New results <ready>')
        self.assertIsNone(frame.signature)
        self.assertFalse(frame.pending)
        self.assertIn('New results &lt;ready&gt;',frame.browser.SetPage.call_args.args[0])

    def test_preview_load_and_error_callbacks_do_not_read_javascript(self):
        frame=SimpleNamespace(pending=True,signature='digest',on_loaded=Mock(),on_error=Mock())
        event=Mock();event.GetString.return_value='navigation failed'
        ReportPreview._loaded(frame,event);ReportPreview._loaded(frame,event)
        frame.on_loaded.assert_called_once_with('digest')
        frame.pending=True;ReportPreview._error(frame,event)
        frame.on_error.assert_called_once_with('navigation failed')
        self.assertFalse(frame.pending)


if __name__=='__main__': unittest.main()
