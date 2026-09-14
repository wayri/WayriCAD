"""Opt-in real KiCad tests; explicitly skipped in the supplied build environment.

Run inside a KiCad 10 Python environment initialized with pcbnew/wx, setting
WAYRICAD_EMBED3D_NATIVE_TESTS=1 and WAYRICAD_EMBED3D_NO_REGISTER=1. Use a disposable project.
No current-board mutation occurs in the two tests below.
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

AVAILABLE = importlib.util.find_spec('pcbnew') is not None and os.environ.get('WAYRICAD_EMBED3D_NATIVE_TESTS') == '1'


@unittest.skipUnless(AVAILABLE, 'Real KiCad 10 runtime not available/enabled; native integration NOT verified')
class NativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        import pcbnew
        from embed_3d_plugin.native import NativeBridge
        from embed_3d_plugin.paths import Resolver
        from embed_3d_plugin.core import Planner
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.bridge = NativeBridge(pcbnew)
        self.model = self.root/'box.wrl'
        self.model.write_bytes(b'#VRML V2.0 utf8\nShape { geometry Box { size 1 2 3 } }\n')
        seed = '(footprint "NativeTest" (version 20241229) (generator pcbnew) (layer "F.Cu") (model "'+str(self.model).replace('\\', '/')+'" (offset (xyz -1 2 3)) (scale (xyz 0.5 2 3)) (rotate (xyz 10 20 -30))))'
        fp = self.bridge.deserialize(seed)
        self.text = self.bridge.serialize(fp)
        self.plan = Planner(Resolver(self.root)).scan(self.text)
    def tearDown(self): self.tmp.cleanup()
    def test_native_parse_preserves_payload_and_transforms(self):
        self.bridge.validate_file(self.plan, self.plan.build())
    def test_native_portable_library_export(self):
        result = self.bridge.export_library([self.plan], self.root/'NativeTest.pretty')
        self.assertEqual(len(list(result.glob('*.kicad_mod'))), 1)

    def test_repeated_detached_parse_cleanup_preserves_native_types(self):
        import pcbnew
        witness = pcbnew.BOARD()
        for _ in range(8):
            fp = self.bridge.deserialize(self.text)
            self.assertIsInstance(fp, pcbnew.FOOTPRINT)
            self.bridge.release_detached()
            self.assertIsInstance(witness.m_Uuid, pcbnew.KIID)

    def test_cleanup_keeps_transferred_board_footprint(self):
        import pcbnew
        self.bridge.board = pcbnew.BOARD()
        fp = self.bridge.deserialize(self.text)
        self.bridge.board.Add(fp)
        before = self.bridge.uid(fp)
        self.bridge.release_detached()
        self.assertEqual(len(list(self.bridge.board.GetFootprints())), 1)
        self.assertEqual(self.bridge.uid(fp), before)


if __name__ == '__main__': unittest.main()
