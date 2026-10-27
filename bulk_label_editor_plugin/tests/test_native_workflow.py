"""Native wx/SWIG acceptance on synthetic boards, never user projects."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

try:
    import pcbnew
    import wx
except ImportError:
    pcbnew = wx = None


@unittest.skipUnless(pcbnew is not None and wx is not None, "Requires KiCad Python and wxPython")
class NativeLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import before creating wx.App: this is not KiCad's registration host.
        from bulk_label_editor_plugin.bulk_label_editor_plugin import BulkLabelEditorFrame
        cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        from bulk_label_editor_plugin.bulk_label_editor_plugin import BulkLabelEditorFrame
        self.board = pcbnew.BOARD()
        self.net = pcbnew.NETINFO_ITEM(self.board, "BUS[0]")
        self.board.Add(self.net)
        for index in (1, 2):
            fp = pcbnew.FOOTPRINT(self.board)
            fp.SetReference(f"R{index}")
            fp.SetValue("10k")
            self.board.Add(fp)
            pad = pcbnew.PAD(fp)
            pad.SetNumber("1")
            pad.SetNet(self.net)
            fp.Add(pad)
        self.text = pcbnew.PCB_TEXT(self.board)
        self.text.SetText("CH1_MAIN")
        self.board.Add(self.text)
        shape = pcbnew.PCB_SHAPE(self.board)
        self.board.Add(shape)
        self.frame = BulkLabelEditorFrame(None, self.board)
        self.frame.Show()
        self.app.Yield()

    def tearDown(self):
        self.frame.Destroy()
        self.app.Yield()

    def test_startup_browses_text_and_nets_without_example_filter(self):
        self.assertEqual(self.frame.match_text.GetValue(), "")
        self.assertEqual(len(self.frame.matches), 3)
        self.assertFalse(self.frame.apply_button.IsEnabled())
        self.assertEqual([row.name for row in self.frame.net_rows], ["BUS[0]"])
        self.assertEqual(self.frame.net_rows[0].pads, 2)
        self.assertEqual(self.frame.net_rows[0].terminals, ("R1.1", "R2.1"))

    def test_native_apply_undo_redo_stale_and_geometry_preserved(self):
        before = [(fp.m_Uuid.AsString(), tuple(fp.GetPosition()), len(fp.Pads())) for fp in self.board.GetFootprints()]
        self.frame.match_text.ChangeValue("CH*_MAIN")
        self.frame.replacement_text.ChangeValue("BUS*_REDUNDANT")
        self.frame.on_preview(None)
        self.assertEqual(len(self.frame.reviewed_changes), 1)
        self.frame.on_apply(None)
        self.assertEqual(self.text.GetText(), "BUS1_REDUNDANT")
        self.frame.on_undo(None)
        self.assertEqual(self.text.GetText(), "CH1_MAIN")
        self.frame.on_redo(None)
        self.assertEqual(self.text.GetText(), "BUS1_REDUNDANT")
        self.assertEqual(before, [(fp.m_Uuid.AsString(), tuple(fp.GetPosition()), len(fp.Pads())) for fp in self.board.GetFootprints()])
        self.assertEqual([pad.GetNetname() for fp in self.board.GetFootprints() for pad in fp.Pads()], ["BUS[0]", "BUS[0]"])

    def test_net_search_and_selection_excludes_other_objects(self):
        self.frame.net_search.ChangeValue("BUS[*]")
        self.frame.on_net_search(None)
        self.assertEqual(len(self.frame.net_table.rows), 1)
        self.text.SetSelected()
        self.frame.net_table.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
        self.frame.on_select_nets(None)
        self.assertFalse(self.text.IsSelected())
        self.assertTrue(all(pad.IsSelected() for fp in self.board.GetFootprints() for pad in fp.Pads()))
        self.frame.net_search.ChangeValue("MISSING")
        self.frame.on_net_search(None)
        self.assertEqual(self.frame.net_table.GetItemCount(), 0)

    def test_ipc_generic_text_kind_reaches_filtered_preview(self):
        from bulk_label_editor_plugin.bulk_label_editor_plugin import BulkLabelEditorFrame
        from types import SimpleNamespace
        # Official IPC facade uses this generic class name for text and shapes.
        class Item:
            def GetText(self): return "CHANNEL_MAIN"
            def SetText(self, text): pass
        frame = SimpleNamespace(board=SimpleNamespace(GetDrawings=lambda: [Item()]), items=[])
        BulkLabelEditorFrame._add_board_text(frame)
        self.assertEqual(frame.items[0].kind, "PCB text")
        self.frame.items = frame.items
        self.frame.match_text.ChangeValue("CHANNEL_*")
        self.frame.replacement_text.ChangeValue("PORT_*")
        self.frame.on_preview(None)
        self.assertEqual(self.frame.reviewed_changes[0][2], "PORT_MAIN")

    def test_saved_board_cli_and_reload_do_not_modify_source(self):
        from bulk_label_editor_plugin.cli import main
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "Example.kicad_pcb"
            pcbnew.SaveBoard(str(path), self.board)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(main(["nets", str(path), "--search", "BUS[*]"]), 0)
            result = json.loads(stream.getvalue())
            self.assertEqual(result["nets"][0]["pads"], 2)
            self.assertEqual(result["source_sha256"], before)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_real_ipc_facade_startup_refresh_and_apply(self):
        from bulk_label_editor_plugin.bulk_label_editor_plugin import BulkLabelEditorFrame
        from wayricad_runtime.ipc import Board
        from types import SimpleNamespace
        class Field: pass
        class Text:
            def __init__(self):
                self.id = SimpleNamespace(value="text-uuid")
                self.value = "CH3_MAIN"
        class Shape:
            id = SimpleNamespace(value="shape-uuid")
        text = Text()
        names = ["VCC"]
        updates = []
        raw = SimpleNamespace(get_nets=lambda: [SimpleNamespace(name=name) for name in names],
                              get_footprints=lambda: [], get_text=lambda: [text],
                              get_shapes=lambda: [Shape()], get_tracks=lambda: [],
                              get_vias=lambda: [], get_zones=lambda: [],
                              update_items=lambda values: updates.extend(values) or values)
        frame = BulkLabelEditorFrame(None, Board(raw, SimpleNamespace(Field=Field)))
        try:
            self.assertEqual([item.current for item in frame.matches], ["CH3_MAIN"])
            names.append("ADDED_AFTER_START")
            frame.on_refresh(None)
            self.assertEqual([row.name for row in frame.net_rows], ["ADDED_AFTER_START", "VCC"])
            frame.match_text.ChangeValue("CH*_MAIN")
            frame.replacement_text.ChangeValue("PORT*_MAIN")
            frame.on_preview(None)
            frame.on_apply(None)
            self.assertEqual(text.value, "PORT3_MAIN")
            self.assertEqual(len(updates), 1)
            frame.on_undo(None)
            self.assertEqual(text.value, "CH3_MAIN")
        finally:
            frame.Destroy()

    def test_selected_footprint_filter_uses_identity_not_duplicate_ref(self):
        footprints = list(self.board.GetFootprints())
        for fp in footprints:
            fp.SetReference("R?")
        footprints[0].SetSelected()
        self.frame.only_selected.SetValue(True)
        self.frame.refresh_items()
        self.assertEqual(len(self.frame.matches), 1)
        self.assertEqual(self.frame.matches[0].owner_id, footprints[0].m_Uuid.AsString())
        self.frame.match_text.ChangeValue("R*")
        self.frame.replacement_text.ChangeValue("X*")
        self.frame.on_preview(None)
        self.frame.on_apply(None)
        self.assertEqual(footprints[0].GetReference(), "X?")
        self.frame.on_undo(None)
        self.assertEqual([fp.GetReference() for fp in footprints], ["R?", "R?"])

    def test_footprint_text_selection_and_group_deselection(self):
        from bulk_label_editor_plugin.selection_utils import select_items
        fp = next(iter(self.board.GetFootprints()))
        text = pcbnew.PCB_TEXT(fp)
        text.SetText("TEST")
        fp.Add(text)
        group = pcbnew.PCB_GROUP(self.board)
        self.board.Add(group)
        group.SetSelected()
        self.assertEqual(select_items(self.board, [text]), 1)
        self.assertTrue(text.IsSelected())
        self.assertFalse(group.IsSelected())

    def test_sort_selected_apply_and_narrow_view(self):
        self.frame.SetSize((900, 640))
        self.frame.Layout()
        self.frame.match_text.ChangeValue("R*")
        self.frame.replacement_text.ChangeValue("X*")
        self.frame.on_preview(None)
        self.frame.preview.sort_column = 2
        self.frame.preview.descending = True
        self.frame.preview.set_rows(self.frame.preview.rows)
        self.assertEqual(self.frame.preview.rows[0][2], "R2")
        self.frame.preview.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
        self.frame.on_apply(None, selected_only=True)
        self.assertEqual(sorted(fp.GetReference() for fp in self.board.GetFootprints()), ["R1", "X2"])
        self.frame.notebook.SetSelection(1)
        self.app.Yield()
        self.assertGreater(self.frame.net_table.GetSize().height, 200)


if __name__ == "__main__":
    unittest.main()
