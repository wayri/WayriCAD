"""Saved-board multisink extraction through the production native mesh/solver."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from quick_pi_plugin.service import execute


NATIVE = all(importlib.util.find_spec(name) for name in ('pcbnew', 'vtk', 'numpy', 'scipy', 'matplotlib'))


@unittest.skipUnless(NATIVE, 'Requires native KiCad and the Quick PI scientific runtime')
class SavedBoardMultisinkTests(unittest.TestCase):
    def setUp(self):
        import pcbnew as p
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'multisink.kicad_pcb'
        board = p.BOARD()
        net = p.NETINFO_ITEM(board, 'VCC')
        board.Add(net)
        point = lambda x, y: p.VECTOR2I(p.FromMM(x), p.FromMM(y))
        track = p.PCB_TRACK(board)
        track.SetStart(point(0, 0)); track.SetEnd(point(10, 0))
        track.SetWidth(p.FromMM(1)); track.SetLayer(p.F_Cu); track.SetNet(net)
        board.Add(track)
        for ref, x in [('J1', 0), ('U1', 5), ('U2', 10)]:
            fp = p.FOOTPRINT(board); fp.SetReference(ref); board.Add(fp)
            pad = p.PAD(fp); pad.SetNumber('1'); pad.SetPosition(point(x, 0))
            pad.SetSize(point(.5, 1)); pad.SetShape(p.PAD_SHAPE_RECT); pad.SetAttribute(p.PAD_ATTRIB_SMD)
            layers = p.LSET(); layers.AddLayer(p.F_Cu); pad.SetLayerSet(layers); pad.SetNet(net)
            fp.Add(pad)
        p.SaveBoard(str(self.path), board)
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.request = dict(action='solve', board_path=str(self.path), net='VCC', source_terminal='J1.1',
                            source_voltage=3.3, source_current_limit=4, edge_mm=.4,
                            stackup_override=[dict(id=p.F_Cu, z_mm=.0175, thickness_mm=.035),
                                              dict(id=p.B_Cu, z_mm=1.5825, thickness_mm=.035)],
                            sinks=[dict(terminal='U1.1', current_A=1, min_voltage_V=3),
                                   dict(terminal='U2.1', current_A=2, min_voltage_V=3)])

    def test_separate_loads_and_capacity_with_read_only_saved_inputs(self):
        bundle = execute(self.request)
        result = bundle['result']
        self.assertEqual([s['label'] for s in result['sinks']], ['U1.1', 'U2.1'])
        self.assertAlmostEqual(result['source_current_A'], 3, 8)
        self.assertLess(result['sinks'][1]['voltage_V'], result['sinks'][0]['voltage_V'])
        self.assertLess(result['energy_relative_error'], 1e-6)
        self.assertTrue(result['feasibility']['feasible'])
        self.assertEqual(bundle['geometry']['source_sha256'], self.before)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)
        limited = execute({**self.request, 'source_current_limit': 2.5})
        self.assertFalse(limited['result']['feasibility']['operating_point_valid'])
        self.assertEqual([s['current_A'] for s in limited['result']['sinks']], [1, 2])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)

    def test_label_uuid_alias_cannot_duplicate_a_load(self):
        inventory = execute(dict(action='inspect', board_path=str(self.path)))
        identity = next(t['id'] for t in inventory['terminals'] if t['label']=='U1.1')
        request = {**self.request, 'sinks': [dict(terminal='U1.1', current_A=1), dict(terminal=identity, current_A=1)]}
        with self.assertRaisesRegex(ValueError, 'Repeated sink identity'): execute(request)

    def test_legacy_source_current_limit_and_voltage_window_are_preserved(self):
        request = {k:v for k,v in self.request.items() if k!='sinks'}
        result = execute({**request, 'sink_terminal':'U2.1', 'sink_current':2,
                          'source_current_limit':1, 'sink_min_voltage':3.299})['result']
        self.assertEqual(result['total_sink_current_A'], 2)
        self.assertTrue(result['feasibility']['source_current_limit_exceeded'])
        self.assertFalse(result['sinks'][0]['within_voltage_limits'])


if __name__ == '__main__': unittest.main()
