from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

try:
    import pcbnew
except ImportError:  # pragma: no cover - pcbnew ships inside KiCad only
    pcbnew = None

from test_point_descriptor_plugin.fixture import FixturePoint, generate_fixture_board


class FixtureGeneratorTests(unittest.TestCase):
    @unittest.skipUnless(pcbnew is not None, "pcbnew is only available inside KiCad")
    def test_fixture_contains_probe_edge_channels_and_routing(self):
        text = generate_fixture_board([
            FixturePoint("TP1", "1", "SDA", 10.0, 20.0),
            FixturePoint("TP2", "1", "SCL", 12.0, 24.0),
        ], "P75 spring probe")
        self.assertIn('(net 1 "SDA")', text)
        self.assertIn('KiWay:Probe_TP1', text)
        self.assertIn('KiWay:Edge_Channel_2', text)
        self.assertEqual(6, text.count("  (segment "))
        self.assertIn('(layer "Edge.Cuts")', text)
        if pcbnew is None:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".kicad_pcb", delete=False, encoding="utf-8") as handle:
            handle.write(text); path = Path(handle.name)
        try:
            board = pcbnew.LoadBoard(str(path))
            self.assertEqual(4, len(list(board.GetFootprints())))
        finally:
            path.unlink(missing_ok=True)

    def test_fixture_rejects_empty_plan(self):
        with self.assertRaises(ValueError):
            generate_fixture_board([], "Custom")


if __name__ == "__main__":
    unittest.main()
