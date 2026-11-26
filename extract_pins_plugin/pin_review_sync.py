"""Refresh reviewed pin data in bounded batches from the originating PCB editor."""
import hashlib
from pathlib import Path
import threading

import wx
from wayricad_runtime.context import connect, redact_error, saved_board
from wayricad_runtime.editor_refresh import source_stamp


def signature(item):
    return hashlib.sha256(item.proto.SerializeToString(deterministic=True)).digest()


class PinReviewSync:
    """Check only reviewed footprints for unsaved edits; a save checks the full scope."""

    def __init__(self, frame, path, origin):
        self.frame = frame
        self.path = Path(path).resolve()
        self.origin = origin
        self.expected = None
        self.keys = []
        self.offset = 0
        self.running = False
        self.closed = False
        self.timer = wx.Timer(frame)
        frame.Bind(wx.EVT_TIMER, self.poll, self.timer)
        self.timer.Start(1250)

    def clear(self):
        self.expected = None

    def review(self, footprints):
        self.expected = {fp.m_Uuid.AsString(): signature(fp.raw) for fp in footprints}
        self.keys = list(self.expected)
        self.offset = 0
        self.stamp = source_stamp(self.path)

    def stop(self):
        self.closed = True
        self.clear()
        self.timer.Stop()

    def poll(self, event=None):
        expected = self.expected
        if self.closed or expected is None or self.running:
            return
        if source_stamp(self.path) != self.stamp:
            self.refresh()
            return
        if not self.keys:
            return
        chunk = self.keys[self.offset:self.offset + 24]
        self.offset = (self.offset + len(chunk)) % len(self.keys)
        self.running = True

        def read():
            changed = False
            error = None
            try:
                from kipy.proto.common.types import KIID
                client = connect(launch_context=self.origin, timeout_ms=3000)
                if saved_board(client) != self.path:
                    raise ValueError("The originating PCB Editor changed boards. Reopen Pin Extractor.")
                items = client.get_board().get_items_by_id([KIID(value=value) for value in chunk])
                actual = {item.id.value: signature(item) for item in items}
                changed = any(actual.get(key) != expected[key] for key in chunk)
            except Exception as exc:
                error = redact_error(exc)
            if not self.closed:
                wx.CallAfter(self.finish, expected, changed, error)

        threading.Thread(target=read, name="Pin Extractor review", daemon=True).start()

    def finish(self, expected, changed, error):
        self.running = False
        if self.closed or expected is not self.expected:
            return
        if error:
            self.frame.InvalidatePreview(None)
            self.frame.status_text.SetLabel("Pin preview expired. " + error)
        elif changed:
            self.refresh()

    def refresh(self):
        try:
            self.frame.OnPreviewExtraction(None)
        except Exception as exc:
            self.frame.InvalidatePreview(None)
            self.frame.status_text.SetLabel("Refresh pin preview: " + redact_error(exc))
