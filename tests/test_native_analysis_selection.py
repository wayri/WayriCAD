"""Origin selection hints must not invent saved items or select other items."""
import unittest
from types import SimpleNamespace
from uuid import uuid4
from wayricad_runtime.native_analysis import restore_selection


class Item:
    def __init__(self):
        self.identity = str(uuid4())
        self.m_Uuid = SimpleNamespace(AsString=lambda: self.identity)
        self.selected = False

    def SetSelected(self):
        self.selected = True


class SelectionTests(unittest.TestCase):
    def test_saved_ids_only(self):
        track, footprint, pad = Item(), Item(), Item()
        footprint.Pads = lambda: [pad]
        board = SimpleNamespace(GetTracks=lambda: [track], Zones=lambda: [],
                                GetFootprints=lambda: [footprint])
        restore_selection(board, [pad.identity, str(uuid4())])
        self.assertTrue(pad.selected)
        self.assertFalse(track.selected)
        self.assertFalse(footprint.selected)

    def test_malformed_id_rejected(self):
        with self.assertRaises(ValueError):
            restore_selection(None, ['not-a-board-id'])

    def test_selection_budget(self):
        with self.assertRaisesRegex(ValueError, '200'):
            restore_selection(None, [str(uuid4()) for _ in range(201)])
