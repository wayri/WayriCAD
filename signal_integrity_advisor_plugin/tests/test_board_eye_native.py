"""End-to-end board extraction to lossy-eye checks on disposable native PCBs.

The synthetic stackup and filled reference polygons are explicit test inputs.
These tests do not qualify a manufactured board or a memory interface.
"""
import hashlib
import math
from pathlib import Path
import tempfile
import unittest

try:
    import pcbnew as pcb
except ImportError:
    pcb = None

try:
    import numpy
except ImportError:
    numpy = None


@unittest.skipIf(pcb is None or numpy is None, 'Native KiCad and NumPy required')
class NativeBoardEyeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'channel.kicad_pcb'

    @staticmethod
    def point(x, y):
        return pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y))

    def make_board(self, *, width=.2, vias=False, stub=False, planes=True):
        """Create native saved copper with two source/receiver pads and four layers."""
        board = pcb.BOARD()
        board.SetCopperLayerCount(4)
        signal = pcb.NETINFO_ITEM(board, 'DATA', 1)
        ground = pcb.NETINFO_ITEM(board, 'GND', 2)
        board.Add(signal)
        board.Add(ground)
        for reference, x in (('U1', 5), ('U2', 65)):
            footprint = pcb.FOOTPRINT(board)
            footprint.SetReference(reference)
            footprint.SetPosition(self.point(x, 10))
            board.Add(footprint)
            pad = pcb.PAD(footprint)
            pad.SetNumber('1')
            pad.SetAttribute(pcb.PAD_ATTRIB_SMD)
            pad.SetShape(pcb.PAD_SHAPE_CIRCLE)
            pad.SetSize(self.point(.6, .6))
            layers = pcb.LSET()
            layers.AddLayer(pcb.F_Cu)
            pad.SetLayerSet(layers)
            pad.SetPosition(self.point(x, 10))
            pad.SetNet(signal)
            footprint.Add(pad)

        def track(start, end, layer=pcb.F_Cu):
            item = pcb.PCB_TRACK(board)
            item.SetStart(self.point(*start))
            item.SetEnd(self.point(*end))
            item.SetLayer(layer)
            item.SetWidth(pcb.FromMM(width))
            item.SetNet(signal)
            board.Add(item)

        if vias:
            for x in (25, 45):
                via = pcb.PCB_VIA(board)
                via.SetPosition(self.point(x, 10))
                via.SetWidth(pcb.F_Cu, pcb.FromMM(.6))
                via.SetDrill(pcb.FromMM(.3))
                via.SetLayerPair(pcb.F_Cu, pcb.B_Cu)
                via.SetNet(signal)
                board.Add(via)
            track((5, 10), (25, 10))
            track((25, 10), (45, 10), pcb.B_Cu)
            track((45, 10), (65, 10))
        else:
            # Three physical segments allow a real branch at an endpoint without
            # requiring the extraction layer to infer an interior junction.
            for start, end in ((5, 25), (25, 45), (45, 65)):
                track((start, 10), (end, 10))
        if stub:
            track((25, 10), (25, 13))
        if planes:
            for layer in (pcb.In1_Cu, pcb.In2_Cu):
                chain = pcb.SHAPE_LINE_CHAIN()
                for xy in ((0, 0), (70, 0), (70, 20), (0, 20)):
                    chain.Append(self.point(*xy))
                chain.SetClosed(True)
                polygon = pcb.SHAPE_POLY_SET()
                polygon.AddOutline(chain)
                zone = pcb.ZONE(board)
                zone.SetLayer(layer)
                zone.SetNet(ground)
                zone.Outline().Append(polygon)
                zone.SetFilledPolysList(layer, polygon)
                zone.SetIsFilled(True)
                board.Add(zone)
        pcb.SaveBoard(str(self.source), board)
        stackup = '''(stackup
          (layer "F.Cu" (type "copper") (thickness 0.035))
          (layer "dielectric 1" (type "prepreg") (thickness 0.2) (epsilon_r 4.2))
          (layer "In1.Cu" (type "copper") (thickness 0.035))
          (layer "dielectric 2" (type "core") (thickness 1.1) (epsilon_r 4.2))
          (layer "In2.Cu" (type "copper") (thickness 0.035))
          (layer "dielectric 3" (type "prepreg") (thickness 0.2) (epsilon_r 4.2))
          (layer "B.Cu" (type "copper") (thickness 0.035)))'''
        text = self.source.read_text(encoding='utf-8')
        self.assertIn('(setup', text)
        self.assertNotIn('(stackup', text)
        self.source.write_text(text.replace('(setup', '(setup ' + stackup, 1), encoding='utf-8')
        return pcb.LoadBoard(str(self.source))

    def analyze(self, board, **inputs):
        from signal_integrity_advisor_plugin.quick_si import analyze
        before = hashlib.sha256(self.source.read_bytes()).digest()
        settings = dict(eye_bitrate_mbps=1000, eye_swing_v=1., source_ohm=50., rise_ns=.1)
        settings.update(inputs)
        report, path = analyze(board, 'DATA', 'U1.1', 'U2.1', **settings)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), before)
        return report, path

    def test_saved_reference_geometry_is_used_for_board_eye(self):
        report, path = self.analyze(self.make_board())
        self.assertTrue(report['circuit_topology']['complete'])
        self.assertEqual(path.track_count, 3)
        self.assertEqual(path.via_count, 0)
        self.assertAlmostEqual(path.length_mm, 60., places=6)
        self.assertTrue(all(section['reference_layer'] == 'In1.Cu' for section in path.segments))
        self.assertTrue(all(section['status'] == 'ok' for section in path.segments))
        eye = report['eye']
        self.assertEqual(eye['status'], 'SIMULATED', eye.get('reason'))
        self.assertTrue(eye['traces_v'])
        self.assertTrue(all(math.isfinite(v) for trace in eye['traces_v'] for v in trace))
        self.assertGreater(eye['center_opening_v'], 0)

    def test_changing_actual_width_changes_extracted_resistance_and_eye(self):
        narrow_report, narrow_path = self.analyze(self.make_board(width=.15))
        wide_report, wide_path = self.analyze(self.make_board(width=.4))
        self.assertEqual(narrow_report['eye']['status'], 'SIMULATED')
        self.assertEqual(wide_report['eye']['status'], 'SIMULATED')
        self.assertAlmostEqual(narrow_path.resistance_ohm / wide_path.resistance_ohm,
                               .4 / .15, places=6)
        self.assertNotEqual(narrow_report['eye']['traces_v'], wide_report['eye']['traces_v'])
        difference = max(abs(a - b)
            for left, right in zip(narrow_report['eye']['traces_v'], wide_report['eye']['traces_v'])
            for a, b in zip(left, right))
        self.assertGreater(difference, .001)

    def test_extra_copper_stub_cannot_be_silently_omitted(self):
        report, _ = self.analyze(self.make_board(stub=True))
        self.assertFalse(report['circuit_topology']['complete'])
        self.assertEqual(report['eye']['status'], 'UNAVAILABLE')
        self.assertNotIn('traces_v', report['eye'])

    def test_missing_reference_copper_does_not_get_an_ideal_eye(self):
        report, _ = self.analyze(self.make_board(planes=False))
        self.assertEqual(report['eye']['status'], 'UNAVAILABLE')
        self.assertNotIn('traces_v', report['eye'])

    def test_via_eye_requires_reviewed_loop_inductance_and_capacitance(self):
        board = self.make_board(vias=True)
        report, path = self.analyze(board)
        self.assertEqual(path.via_count, 2)
        self.assertEqual(report['eye']['status'], 'UNAVAILABLE')
        self.assertNotIn('traces_v', report['eye'])
        reviewed, _ = self.analyze(board, eye_via_l_nh=.5, eye_via_c_pf=.2)
        self.assertEqual(reviewed['eye']['status'], 'SIMULATED', reviewed['eye'].get('reason'))
        caveats = ' '.join(reviewed['eye'].get('assumptions', []) + reviewed['eye'].get('limitations', []))
        self.assertIn('via', caveats.lower())
        self.assertTrue(any(word in caveats.lower() for word in ('approx', 'assum', 'review')))

    def test_lightly_damped_step_includes_the_verified_settled_region(self):
        report, _ = self.analyze(self.make_board(), source_ohm=5.)
        eye = report['eye']
        self.assertEqual(eye['status'], 'SIMULATED', eye.get('reason'))
        step = eye['step_response']
        self.assertGreater(step['time_ns'][-1], 4 * eye['ui_ns'])
        self.assertAlmostEqual(step['voltage_v'][-1], eye['numerics']['dc_receiver_v'], delta=.002)


if __name__ == '__main__':
    unittest.main()
