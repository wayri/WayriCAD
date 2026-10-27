"""PCB net discovery must work without GUI/SWIG and never hide read failures."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from bulk_label_editor_plugin.inventory import InventoryError, collect_nets


def item(name, uid, kind="PCB_TRACK", number="1", rule_area=False):
    return SimpleNamespace(GetNetname=lambda: name,
                           m_Uuid=SimpleNamespace(AsString=lambda: uid),
                           GetClass=lambda: kind, GetNumber=lambda: number,
                           GetIsRuleArea=lambda: rule_area)


class Board:
    def __init__(self):
        self.names = ["", "BUS[0]", "GND", "UNUSED"]
        self.calls = {}
        self.active = False
        self.footprints = [SimpleNamespace(GetReference=lambda: "U1", Pads=self.pads)]
        self.tracks = [item("BUS[0]", "track"), item("GND", "arc", "PCB_ARC"),
                       item("GND", "via", "PCB_VIA"), item("", "no-net")]
        self.zones = [item("GND", "zone"), item("GND", "rule", rule_area=True)]

    def count(self, key, values):
        self.calls[key] = self.calls.get(key, 0) + 1
        return values

    def GetNetsByName(self):
        self.count("names", [])
        return {name: SimpleNamespace(GetNetname=lambda name=name: name) for name in self.names}

    def pads(self):
        return self.count("pads", [item("BUS[0]", "pad1"), item("GND", "pad2", number="2")])

    def GetFootprints(self):
        return self.count("footprints", self.footprints)

    def GetTracks(self):
        return self.count("tracks", self.tracks)

    def Zones(self):
        return self.count("zones", self.zones)


class NetInventoryTests(unittest.TestCase):
    def test_native_members_and_named_unused_nets(self):
        board = Board()
        rows = collect_nets(board)
        self.assertEqual([row.name for row in rows], ["BUS[0]", "GND", "UNUSED"])
        ground = rows[1]
        self.assertEqual((ground.pads, ground.tracks, ground.vias, ground.zones, ground.members), (1, 1, 1, 1, 4))
        self.assertEqual(ground.member_ids, ("arc", "pad2", "via", "zone"))
        self.assertEqual(ground.terminals, ("U1.2",))
        self.assertEqual(board.calls, dict(names=1, footprints=1, pads=1, tracks=1, zones=1))

    def test_empty_board_is_a_valid_empty_inventory(self):
        board = Board()
        board.names = [""]
        board.footprints = board.tracks = board.zones = []
        self.assertEqual(collect_nets(board), [])

    def test_ipc_refresh_reads_live_names_instead_of_startup_cache(self):
        board = Board()
        board.net_names = {0: "", 1: "OLD"}
        board.raw = SimpleNamespace(get_nets=lambda: board.count("live", [SimpleNamespace(name=n) for n in board.names]))

        @contextmanager
        def snapshot():
            self.assertFalse(board.active)
            board.active = True
            try:
                yield
            finally:
                board.active = False
        board.read_snapshot = snapshot
        self.assertEqual(len(collect_nets(board)), 3)
        board.names.append("NEW")
        self.assertIn("NEW", [row.name for row in collect_nets(board)])
        self.assertNotIn("OLD", [row.name for row in collect_nets(board)])
        self.assertFalse(board.active)
        self.assertNotIn("names", board.calls)
        self.assertEqual(board.calls["live"], 3)
        self.assertEqual(board.net_names, {0: "", 1: "OLD"})

    def test_failed_ipc_net_read_is_not_reported_as_no_nets(self):
        board = Board()
        def fail():
            raise RuntimeError("editor unavailable")
        board.raw = SimpleNamespace(get_nets=fail)
        with self.assertRaisesRegex(InventoryError, "live net names.*editor unavailable"):
            collect_nets(board)

    def test_unsupported_and_malformed_net_api_are_diagnostic(self):
        with self.assertRaisesRegex(InventoryError, "does not expose PCB nets"):
            collect_nets(SimpleNamespace())
        board = Board()
        board.raw = SimpleNamespace(get_nets=lambda: 7)
        with self.assertRaisesRegex(InventoryError, "live net names"):
            collect_nets(board)
        board.raw = SimpleNamespace(get_nets=lambda: [7])
        with self.assertRaisesRegex(InventoryError, "unsupported net record"):
            collect_nets(board)

    def test_membership_collection_failure_is_not_silently_skipped(self):
        board = Board()
        def fail():
            raise RuntimeError("zone read rejected")
        board.Zones = fail
        with self.assertRaisesRegex(InventoryError, "zones.*zone read rejected"):
            collect_nets(board)

    def test_no_net_ignored_and_uuid_required_for_cross_selection(self):
        board = Board()
        board.tracks.append(SimpleNamespace(GetNetname=lambda: ""))
        collect_nets(board)
        board.tracks.append(SimpleNamespace(GetNetname=lambda: "GND"))
        with self.assertRaisesRegex(InventoryError, "no UUID"):
            collect_nets(board)

    def test_duplicate_uuid_rejected(self):
        board = Board()
        board.tracks.append(item("GND", "via"))
        with self.assertRaisesRegex(InventoryError, "duplicate"):
            collect_nets(board)


if __name__ == "__main__":
    unittest.main()
