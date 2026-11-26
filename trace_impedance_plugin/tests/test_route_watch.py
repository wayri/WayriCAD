"""Test the live route worker with native KiCad geometry and a controlled editor copy."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import pcbnew
    from trace_impedance_plugin.route_watch import WatchedPath
except ImportError:
    pcbnew = None

import test_via_geometry


@unittest.skipIf(pcbnew is None, 'native KiCad wx runtime required')
class LivePathTests(unittest.TestCase):
    def test_uses_editor_copy_and_rejects_a_superseded_result(self):
        fixture = test_via_geometry.NativeGeometryTests()
        board, net = fixture.board()
        starts = [fixture.pad(board, net, ref, x, 1, pcbnew.F_Cu)
                  for ref, x in [('J1', 1), ('J2', 5)]]
        fixture.track(board, net, (1_000_000, 1_000_000), (5_000_000, 1_000_000), pcbnew.F_Cu)
        endpoints = tuple(pad.m_Uuid.AsString() for pad in starts)
        with TemporaryDirectory(prefix='trace-rlc-live-') as directory:
            original = Path(directory) / 'original.kicad_pcb'
            current = original.with_name('editor-copy.kicad_pcb')
            pcbnew.SaveBoard(str(original), board)
            original_bytes = original.read_bytes()
            board.GetTracks()[0].SetWidth(400_000)
            pcbnew.SaveBoard(str(current), board)
            origin = SimpleNamespace(path=original, launch_context=object())
            request = WatchedPath(origin, 'SIG', endpoints, 100.0, 'Auto', '')
            route = 'active-revision'

            @contextmanager
            def capture(path, context, *, watch_nets):
                self.assertEqual((path, context, watch_nets), (original, origin.launch_context, ('SIG',)))
                yield current, {'mode': 'editor-copy', 'route_stamp': 'active-revision'}

            with patch('trace_impedance_plugin.route_watch.capture_live_pcb', capture), patch(
                    'trace_impedance_plugin.route_watch.route_stamp', side_effect=lambda *_args: route):
                analysis = request.extract(None, lambda: False)
                _, path, mate, evidence, stamp = analysis
                self.assertAlmostEqual(path.average_width_mm, .4)
                self.assertEqual((path.start_pad, path.end_pad), ('J1.1', 'J2.1'))
                self.assertIsNone(mate)
                self.assertEqual(evidence['mode'], 'editor-copy')
                route = 'edited-again'
                self.assertIsNone(request.extract(stamp, lambda: False))
            self.assertEqual(original.read_bytes(), original_bytes)
