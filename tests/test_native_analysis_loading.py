"""The electrical loader clears a canceled or failed saved-board load."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from wayricad_runtime import native_analysis


def _fixture(tmp_path):
    root = tmp_path / 'trace'
    root.mkdir()
    (root / 'trace_impedance_plugin.py').write_text(
        "class TraceFrame:\n"
        "    def __init__(self, parent, board, saved_board=False):\n"
        "        self.saved_board = saved_board\n", encoding='utf-8')
    return root


def test_saved_board_load_updates_status_before_frame(tmp_path):
    root = _fixture(tmp_path)
    messages = []
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
    pcbnew = SimpleNamespace(LoadBoard=lambda _path: object())
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        _, frame = native_analysis.create_frame(
            root, 'trace_impedance_plugin', tmp_path / 'board.kicad_pcb',
            status=messages.append, cancelled=lambda: False)
    assert messages == ['Preparing the analysis window…']
    assert frame.saved_board


def test_cancel_after_board_read_prevents_analysis_frame(tmp_path):
    root = _fixture(tmp_path)
    closed = [False]
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
    pcbnew = SimpleNamespace(LoadBoard=lambda _path: object())
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        with pytest.raises(native_analysis.LoadingCancelled):
            native_analysis.create_frame(
                root, 'trace_impedance_plugin', tmp_path / 'board.kicad_pcb',
                status=lambda _text: closed.__setitem__(0, True),
                cancelled=lambda: closed[0])


def test_invalid_saved_board_reports_error(tmp_path):
    root = _fixture(tmp_path)
    wx = SimpleNamespace(App=SimpleNamespace(Get=lambda: object()))
    pcbnew = SimpleNamespace(LoadBoard=lambda _path: None)
    with patch.dict(sys.modules, {'wx': wx, 'pcbnew': pcbnew}), \
         patch.object(native_analysis, 'restore_selection'):
        with pytest.raises(ValueError, match='could not load'):
            native_analysis.create_frame(root, 'trace_impedance_plugin',
                                         tmp_path / 'board.kicad_pcb')


def test_native_main_reads_once_before_starting_wx_and_reuses_snapshot(tmp_path):
    path=tmp_path/'board.kicad_pcb';path.write_text('saved fixture')
    order=[];board=object();frame=Mock();app=Mock()
    loading=SimpleNamespace(start=Mock(),stage=Mock(),finish=Mock(),cancelled=False)
    def load(name):
        order.append('native read');assert name==str(path);return board
    def ensure(wx):order.append('wx app');return app
    with patch.dict(sys.modules,{'pcbnew':SimpleNamespace(LoadBoard=Mock(side_effect=load)),'wx':SimpleNamespace()}), \
         patch('wayricad_runtime.loading.ensure_wx_app',side_effect=ensure), \
         patch.object(native_analysis,'_loading_window',return_value=loading), \
         patch.object(native_analysis,'create_frame',return_value=(app,frame)) as create:
        assert native_analysis.main(['--root',str(tmp_path),'--tool','trace_impedance_plugin','--board',str(path)])==0
    assert order==['native read','wx app']
    assert create.call_args.kwargs['loaded_board'] is board
    frame.Show.assert_called_once();app.MainLoop.assert_called_once();loading.finish.assert_called_once()


@pytest.mark.parametrize('deleted',[False,True])
def test_native_main_destroys_unshown_frame_if_source_changes_during_preparation(tmp_path,deleted):
    path=tmp_path/'board.kicad_pcb';path.write_text('original')
    board=object();frame=Mock();app=Mock()
    loading=SimpleNamespace(start=Mock(),stage=Mock(),finish=Mock(),cancelled=False)
    wx=SimpleNamespace(MessageBox=Mock(),OK=1,ICON_ERROR=2)
    def create(*args,**kwargs):
        if deleted:path.unlink()
        else:path.write_text('changed')
        return app,frame
    with patch.dict(sys.modules,{'pcbnew':SimpleNamespace(LoadBoard=Mock(return_value=board)),'wx':wx}), \
         patch('wayricad_runtime.loading.ensure_wx_app',return_value=app), \
         patch.object(native_analysis,'_loading_window',return_value=loading), \
         patch.object(native_analysis,'create_frame',side_effect=create):
        assert native_analysis.main(['--root',str(tmp_path),'--tool','trace_impedance_plugin','--board',str(path)])==1
    frame.Destroy.assert_called_once();frame.Show.assert_not_called();app.MainLoop.assert_not_called()
    wx.MessageBox.assert_called_once();loading.finish.assert_called_once()
