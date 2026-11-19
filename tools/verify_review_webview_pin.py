"""Bounded native Review WebView smoke check against an authorized saved board."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board', type=Path)
    args = parser.parse_args()
    board = args.board.resolve()
    digest = hashlib.sha256(board.read_bytes()).hexdigest()
    import wx
    from review_comments_plugin.web_canvas import WebDesignCanvas
    app = wx.App(False)
    state = dict(loaded=False, requested=False, error=None)

    class Canvas(WebDesignCanvas):
        def message(self, event):
            super().message(event)
            value = json.loads(event.GetString())
            if value.get('type') == 'documentReady':
                state['loaded'] = True
            elif value.get('type') == 'error':
                state['error'] = value.get('message')

    owner = SimpleNamespace(closed=False, busy=False, session=None, target=None,
                            review_theme='light', review_variant='*')
    owner.task = lambda operation, complete, message, **kwargs: complete(operation())
    frame = wx.Frame(None, title='WayriCAD Review source-pin validation', size=(1100, 760))
    canvas = Canvas(frame, owner)
    layout = wx.BoxSizer(wx.VERTICAL)
    layout.Add(canvas, 1, wx.EXPAND)
    frame.SetSizer(layout)
    started = time.monotonic()

    def tick():
        try:
            if state['error']:
                raise RuntimeError(state['error'])
            if canvas.ready and not state['requested']:
                state['requested'] = True
                canvas.load(board)
            if state['loaded']:
                assert canvas.digest == digest
                assert not canvas.can_anchor(quiet=True), 'Read-only preview must not authorize publication'
                assert hashlib.sha256(board.read_bytes()).hexdigest() == digest
                canvas.close()
                frame.Destroy()
                return
            if time.monotonic()-started > 60:
                raise TimeoutError('Native Review viewer did not acknowledge the document: '+canvas.status.GetLabel())
            wx.CallLater(100, tick)
        except Exception as error:
            state['error'] = str(error)
            canvas.close()
            frame.Destroy()

    frame.Show()
    wx.CallLater(100, tick)
    app.MainLoop()
    print(json.dumps(dict(status='FAIL' if state['error'] else 'PASS', **state,
                          source_sha256=digest, source_unchanged=hashlib.sha256(board.read_bytes()).hexdigest()==digest)))
    return int(bool(state['error']) or not state['loaded'])


if __name__ == '__main__':
    raise SystemExit(main())
