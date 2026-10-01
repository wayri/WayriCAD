"""KiCad IPC footprint headers must not hide saved/live design changes."""

import json
from pathlib import Path
import tempfile
import unittest

from manufacturing_readiness_plugin.analysis import FabricatorProfile, comparable_board_tokens, gate_key
from manufacturing_readiness_plugin.verification import capture_inputs


BOARD = '''(kicad_pcb (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (footprint "test" (layer "F.Cu")
    (pad "1" smd rect (size 1 1) (version 7))))'''
PROJECT = json.dumps({'board': {'design_settings': {'rules': {'min_clearance': 0.2}}}})


class IPCSerializationTests(unittest.TestCase):
    def test_transient_footprint_headers_only(self):
        live = BOARD.replace('(layer "F.Cu")',
                             '(version 20260206) (generator "pcbnew") '
                             '(generator_version "10.0.6") (layer "F.Cu")')
        self.assertEqual(comparable_board_tokens(BOARD), comparable_board_tokens(live))
        profile = FabricatorProfile()
        files = {'board.kicad_pcb': BOARD.encode(), 'board.kicad_pro': PROJECT.encode()}
        self.assertEqual(gate_key(files, profile, '', BOARD), gate_key(files, profile, '', live))
        changed_source = dict(files, **{'board.kicad_pcb': BOARD.replace('(version 7)', '(version 8)').encode()})
        self.assertNotEqual(gate_key(files, profile, '', live), gate_key(changed_source, profile, '', live))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'board.kicad_pcb').write_text(BOARD, encoding='utf-8')
            (root / 'board.kicad_pro').write_text(PROJECT, encoding='utf-8')
            captured, _, _ = capture_inputs(root / 'board.kicad_pcb', root, profile, '', live)
            self.assertEqual(captured['board.kicad_pcb'], (root / 'board.kicad_pcb').read_bytes())
            for changed in (live.replace('(size 1 1)', '(size 2 1)'),
                            live.replace('(version 7)', '(version 8)'),
                            live.replace('(layer "F.Cu")', '(layer "B.Cu")')):
                with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'differs'):
                    capture_inputs(root / 'board.kicad_pcb', root, profile, '', changed)


if __name__ == '__main__':
    unittest.main()
