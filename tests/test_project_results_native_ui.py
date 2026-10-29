"""Native saved-library buttons and archive plots never execute a new solve."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
wx = pytest.importorskip('wx')
# Standalone native tests have no GUI log-loop. Keep warnings visible on stderr
# instead of deferring a wx.LogGui message dialog until interpreter teardown.
_NATIVE_LOG=wx.LogStderr()
_PREVIOUS_LOG=wx.Log.SetActiveTarget(_NATIVE_LOG)

from wayricad_runtime.project_results_ui import add_project_results, add_study_results, create_viewer

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'docs/examples/pocket-kivi'


_APP=None


@pytest.fixture(scope='module')
def app():
    global _APP
    _APP=wx.GetApp() or wx.App(False)
    application=_APP
    application.SetExitOnFrameDelete(False)
    yield application


@pytest.fixture
def owner(app):
    frame=wx.Frame(None)
    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    yield frame
    frame.Destroy();app.Yield()


def loaded(name='quick-pi', state='unverified'):
    return dict(bundle=json.loads((EXAMPLES/(name+'.pocket-kivi.json')).read_bytes()),
                receipt=dict(plugin='quick-pi',source_state=state,can_restore=False))


def test_native_saved_pi_plot_and_pin_preserve_original_values(owner, app):
    data=loaded();original=deepcopy(data['bundle'])
    viewer=create_viewer(owner,data)
    try:
        assert viewer.GetTitle()=='Saved simulation • read-only'
        spec=viewer.current_spec()
        event=SimpleNamespace(inaxes=viewer.figure.axes[0],xdata=spec['x'][0],ydata=spec['y'][0],button=1)
        viewer.pin(event)
        assert viewer.pins[0]['value']==original['result']['potential_V'][0]
        assert viewer.bundle==original
        assert not hasattr(viewer,'board') and not hasattr(viewer,'_accept_result')
    finally:viewer.Destroy();app.Yield()


def test_native_thermal_saved_frames_have_exact_time_and_values(owner,app):
    data=loaded('quick-therm-transient','stale');original=deepcopy(data['bundle'])
    viewer=create_viewer(owner,data)
    try:
        index=next(i for i,spec in enumerate(viewer.specs) if spec['kind']=='frames')
        viewer.choice.SetSelection(index);viewer.select_plot(None)
        viewer.time.SetValue(2);viewer.time_changed(None)
        assert viewer.frame_index==2 and 't = 1' in viewer.time_label.GetLabel()
        spec=viewer.current_spec();x,y=spec['cells'][0]
        event=SimpleNamespace(inaxes=viewer.figure.axes[0],xdata=spec['x'][x],ydata=spec['y'][y],button=1)
        viewer.pin(event)
        assert viewer.pins[0]['value']==original['thermal_network']['transient']['frames'][2]['temperatures_c'][0]
        assert viewer.bundle==original
    finally:viewer.Destroy();app.Yield()


def test_native_advanced_tree_expands_only_one_page(owner,app):
    data=dict(bundle={'values':list(range(10000))},receipt={'source_state':'unverified'})
    viewer=create_viewer(owner,data)
    try:
        root=viewer.tree.GetRootItem()
        viewer.expand_data(SimpleNamespace(GetItem=lambda:root))
        values=viewer.tree.GetFirstChild(root)[0]
        viewer.expand_data(SimpleNamespace(GetItem=lambda:values))
        assert viewer.tree.GetChildrenCount(values,False)==101
        assert len(viewer.bundle['values'])==10000
    finally:viewer.Destroy();app.Yield()


def test_buttons_save_exact_complete_bundle_and_load_without_solver(owner,app,tmp_path):
    bundle={'model':'Explicit circuit only','transient':{'times_s':[0,1],'voltage_V':[3.3,None]}}
    status=[]
    actions=add_project_results(owner,owner,owner.GetSizer(),'quick-pi',tmp_path/'board.kicad_pcb',
        lambda:[('Completed circuit',bundle)],certify=False,status=status.append)
    actions.task=lambda operation,done:done(operation())
    actions.on_save()
    assert any('Saved Completed circuit' in value for value in status)
    from wayricad_runtime.project_results import list_results,load_result
    receipts=list_results(tmp_path,plugin='quick-pi')
    assert len(receipts)==1
    assert load_result(tmp_path,receipts[0]['path'])['bundle']==bundle
    dialog=Mock();dialog.__enter__=Mock(return_value=dialog);dialog.__exit__=Mock(return_value=False)
    dialog.ShowModal.return_value=wx.ID_OK;dialog.GetSelection.return_value=0
    result=Mock()
    dialog.GetPath.return_value=receipts[0]['path']
    with patch('wx.FileDialog',return_value=dialog),patch('wayricad_runtime.project_results_ui.create_viewer',return_value=result) as opened:
        actions.on_load()
    result.Show.assert_called_once()
    assert opened.call_args.args[1]['bundle']==bundle
    assert actions.save.GetLabel()=='Save simulation…' and actions.load.GetLabel()=='Load simulation…'


def test_study_hook_retains_actual_result_and_is_idempotent(owner,tmp_path):
    owner.result={'transient':{'times_s':[0,1],'voltage_V':[1,2]}}
    owner.status=wx.StaticText(owner)
    add_study_results(owner,'quick-pi',tmp_path/'board.kicad_pcb')
    actions=owner._project_result_actions
    assert actions.available()[0][1] is owner.result and actions.certify is False
    add_study_results(owner,'quick-pi',tmp_path/'board.kicad_pcb')
    assert owner._project_result_actions is actions




def test_actual_pdn_dialog_receives_archive_hook_with_no_board_load(owner,app,tmp_path):
    pytest.importorskip('pcbnew')
    from quick_pi_plugin.decoupling.pdn_decoupling_plugin import PdnFrame
    from quick_pi_plugin.decoupling.impedance_ui import PdnImpedanceDialog
    owner.board_path=str(tmp_path/'example.kicad_pcb')
    frame=PdnFrame(owner,None,board_loader=Mock(side_effect=AssertionError('No board load expected')))
    checked=[]
    def inspect(dialog):
        assert not dialog._project_result_actions.certify
        assert dialog._project_result_actions.available()==[]
        dialog.result={'rows':[{'frequency_Hz':1000,'impedance_ohm':.2}]}
        assert dialog._project_result_actions.available()[0][1] is dialog.result
        checked.append(True)
        return wx.ID_CANCEL
    with patch.object(PdnImpedanceDialog,'ShowModal',inspect):
        frame.impedance()
    assert checked==[True]
    app.Yield()


def test_si_project_actions_with_explicit_board_api_fixture(owner,app,tmp_path):
    import importlib,sys,types
    # Isolate the package entry point from native editor registration; this unit
    # exercises the real panel against an explicit read-only board API fixture.
    if 'signal_integrity_advisor_plugin' not in sys.modules:
        package=types.ModuleType('signal_integrity_advisor_plugin')
        package.__path__=[str(ROOT/'signal_integrity_advisor_plugin')]
        sys.modules[package.__name__]=package
    module=importlib.import_module('signal_integrity_advisor_plugin.quick_ui')
    path=tmp_path/'example.kicad_pcb'
    path.write_bytes((EXAMPLES/'example.kicad_pcb').read_bytes())
    board=SimpleNamespace(GetFileName=lambda:str(path),GetFootprints=lambda:[],GetTracks=lambda:[])
    engine=SimpleNamespace(_natural_key=str,available_layers=lambda:[])
    class Preview(wx.Panel):
        def show_result(self,result):self.result=result
        def fit(self):pass
        def zoom(self,factor):pass
        def clear_probes(self):pass
    with patch.object(module,'TraceMeasurementEngine',return_value=engine):
        panel=module.QuickSIPanel(owner,board,Preview,saved_board=True)
    assert panel.project_results.project_root==tmp_path
    assert panel.project_results.available()==[]
    report={'status':'SCREENED','eye':{'time_ui':[0,1],'traces_v':[[0,1]]}}
    panel.report=report
    assert panel.project_results.available()[0][1] is report
    assert panel.project_results.save.GetLabel()=='Save simulation…'
    assert panel.project_results.load.GetLabel()=='Load simulation…'
    panel._closed=True;panel.Destroy();app.Yield()
