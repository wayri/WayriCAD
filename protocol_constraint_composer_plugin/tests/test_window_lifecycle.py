"""Late WebView callbacks and wx command-line parsing stay outside closed windows."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from protocol_constraint_composer_plugin import studio_ui, studio_webview


def test_webview_startup_watchdog_stops_with_window():
    frame = object()
    timer = Mock()
    visual = object.__new__(studio_webview.VisualWorkspace)
    visual.frame = frame
    visual.startup_timer = timer
    event = SimpleNamespace(GetEventObject=lambda: frame, Skip=Mock())
    visual._destroyed(event)
    timer.Stop.assert_called_once_with()
    assert visual.frame is None
    event.Skip.assert_called_once_with()
    visual.check_connection()  # Must not touch the deleted frame.


def test_webview_error_switches_to_native_worksheet_without_waiting_for_watchdog():
    frame = SimpleNamespace(IsBeingDeleted=lambda: False, SetStatusText=Mock(), Layout=Mock())
    visual = object.__new__(studio_webview.VisualWorkspace)
    visual.frame = frame
    visual.connected = False
    visual.failed = False
    visual.last_error = ''
    visual.native = Mock()
    visual.back = SimpleNamespace(Hide=Mock())
    event = SimpleNamespace(GetString=lambda: 'CONNECTION_ABORTED', GetURL=lambda: '', Skip=Mock())
    with patch.object(studio_webview.wx, 'CallAfter', side_effect=lambda callback: callback()):
        visual.load_error(event)
    assert visual.failed
    visual.native.assert_called_once_with('workbench')
    assert 'CONNECTION_ABORTED' in frame.SetStatusText.call_args.args[0]
    event.Skip.assert_called_once_with()


def test_standalone_board_argument_is_consumed_before_wx_app():
    board = 'C:/Projects/Example/board.kicad_pcb'
    frame = SimpleNamespace(Show=Mock())

    def app(_redirect):
        assert sys.argv == ['studio_ui.py']
        return SimpleNamespace(MainLoop=Mock())

    with patch.object(sys, 'argv', ['studio_ui.py', board]), \
         patch.object(studio_ui.wx, 'App', side_effect=app), \
         patch.object(studio_ui, 'ConstraintStudioFrame', return_value=frame) as make_frame:
        studio_ui.main()
    make_frame.assert_called_once_with(board_path=board)
    frame.Show.assert_called_once_with()
