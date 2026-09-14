"""Opt-in KiCad 10 integration tests. Never operate on the currently open PCB."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

AVAILABLE = importlib.util.find_spec('pcbnew') is not None and os.environ.get('WAYRICAD_EMBED3D_NATIVE_TESTS') == '1'

@unittest.skipUnless(AVAILABLE, 'Real KiCad 10 runtime unavailable/not enabled; package native parsing not verified')
class NativePackageTests(unittest.TestCase):
    def setUp(self):
        import pcbnew
        from embed_3d_plugin.native import NativeBridge
        self.pcbnew = pcbnew
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.bridge = NativeBridge(pcbnew)
        # A private, allocated board: never mutate pcbnew.GetBoard().
        self.bridge.board = pcbnew.BOARD()
        self.bridge.board.SetFileName(str(self.root/'Test.kicad_pcb'))
        self.model = self.root/'box.wrl'
        self.model.write_bytes(b'#VRML V2.0 utf8\nShape { geometry Box { size 1 2 3 } }\n')
    def tearDown(self): self.tmp.cleanup()

    def make_package(self, back=False, model=True):
        from embed_3d_plugin.core import Planner
        from embed_3d_plugin.paths import Resolver
        from embed_3d_plugin.board_package import Instance, compose, write_package
        ref = str(self.model).replace('\\', '/')
        m = '(model "'+ref+'" (offset (xyz -1 2 3)) (scale (xyz 0.5 2 3)) (rotate (xyz 10 20 -30)))' if model else ''
        layer = 'B.Cu' if back else 'F.Cu'
        seed = '(footprint "Lab:Test" (version 20241229) (generator "pcbnew") (layer "'+layer+'") '+\
               '(at 15 23 127) (pad "1" smd rect (at 1 2) (size 1 2) (layers "'+layer+'")) '+m+')'
        fp = self.bridge.deserialize(seed)
        fp.SetReference('U1')
        self.bridge.board.Add(fp)
        fp.thisown = False
        r = Resolver(self.root)
        sources, pool = self.bridge.sources(False, r)
        plan = Planner(r).scan(sources[0]['text'], 'U1', self.root, pool)
        plan.owner = fp
        definitions = self.bridge.normalize_definitions([{'key': 'U1', 'name': 'Test_1', 'plan': plan,
                                                         'source_id': 'Lab:Test', 'origin': 'board snapshot'}])
        p = compose(self.bridge.board_text(), [Instance(self.bridge.uid(fp), plan, 'U1', 'U1')], definitions, 'Embedded')
        return write_package(p, self.root/'package', 'Test.kicad_pcb', validate=self.bridge.validate_package)

    def test_native_board_pool_footprint_archive_parse_and_save(self):
        self.assertTrue(self.make_package().is_file())

    def test_native_rotated_backside_footprint_package(self):
        self.assertTrue(self.make_package(back=True).is_file())

    def test_native_footprint_without_model_package(self):
        self.assertTrue(self.make_package(model=False).is_file())
