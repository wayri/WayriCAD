"""Check one disposable KiCad IPC plugin action's first window, without editing a board."""
import ctypes
import json
from pathlib import Path
import runpy
import sys
import traceback

if sys.platform == 'win32':
    ctypes.windll.kernel32.SetErrorMode(0x0002)

import wx


def main():
    root, entrypoint, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    result = {'status': 'starting', 'windows': [], 'errors': []}
    output.write_text(json.dumps(result))
    app = wx.App.Get() or wx.App(False)
    original_message = wx.MessageBox

    def message(value, *args, **kwargs):
        result['errors'].append(str(value))
        return wx.ID_OK

    wx.MessageBox = message

    def inspect():
        try:
            windows = [w for w in wx.GetTopLevelWindows() if w and w.IsShown()]
            result['windows'] = [{'title': w.GetTitle(), 'class': type(w).__name__}
                                 for w in windows]
            studio = next((w for w in windows if type(w).__name__ == 'ConstraintStudioFrame'), None)
            if studio is not None:
                visual = getattr(studio, 'visual', None)
                result['visual_workspace'] = {
                    'ready': bool(visual and visual.ready),
                    'connected': bool(visual and visual.connected),
                    'failed': bool(visual and visual.failed),
                    'url': visual.view.GetCurrentURL() if visual else None,
                    'view_shown': bool(visual and visual.view.IsShown()),
                    'last_navigation': visual.last_navigation if visual else None,
                    'last_loaded': visual.last_loaded if visual else None,
                    'last_error': visual.last_error if visual else None,
                }
                if not result['visual_workspace']['connected'] and not result['visual_workspace']['failed'] and not result.get('visual_waited'):
                    result['visual_waited'] = True
                    output.write_text(json.dumps(result, indent=2))
                    wx.CallLater(12000, inspect)
                    return
            result['status'] = 'passed' if windows and not result['errors'] else 'failed'
            if not windows:
                result['error'] = 'No visible plugin window after launch.'
            output.write_text(json.dumps(result, indent=2))
            for window in windows:
                window.Close()
            wx.CallLater(300, app.ExitMainLoop)
        except BaseException:
            result.update(status='failed', traceback=traceback.format_exc())
            output.write_text(json.dumps(result, indent=2))
            app.ExitMainLoop()

    wx.CallLater(2000, inspect)
    try:
        sys.argv = [str(root / entrypoint)]
        runpy.run_path(str(root / entrypoint), run_name='__main__')
    except BaseException:
        result.update(status='failed', traceback=traceback.format_exc())
        output.write_text(json.dumps(result, indent=2))
    finally:
        wx.MessageBox = original_message
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
