"""Board graphics in the IPC facade must not become editable label rows."""
from types import SimpleNamespace
from unittest.mock import patch
import sys

import pytest

pytest.importorskip("wx")
with patch.dict(sys.modules, {"pcbnew": SimpleNamespace(ActionPlugin=object)}):
    from bulk_label_editor_plugin.bulk_label_editor_plugin import BulkLabelEditorFrame


def test_board_rectangle_without_text_is_skipped():
    class Rectangle:
        def GetText(self):
            raise AttributeError("'BoardRectangle' object has no attribute 'value'")

        def SetText(self, value):
            raise AssertionError("A rectangle must never be edited as text")

    class BoardText:
        def GetText(self):
            return "Existing label"

        def SetText(self, value):
            pass

    frame = SimpleNamespace(board=SimpleNamespace(GetDrawings=lambda: [Rectangle(), BoardText()]), items=[])
    BulkLabelEditorFrame._add_board_text(frame)
    assert len(frame.items) == 1
    assert frame.items[0].current == "Existing label"
