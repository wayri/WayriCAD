"""Control-flow tests using fakes, NOT a substitute for native KiCad testing."""
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from embed_3d_plugin.core import Planner
from embed_3d_plugin.paths import Resolver
from embed_3d_plugin.native import NativeBridge


class FakeFootprint:
    def __init__(self, text):
        self.text = text
        self.group = object()
        self.parent = None
    def SwapItemData(self, image):
        self.text, image.text = image.text, self.text
    def SetParent(self, board): self.parent = board
    def SetParentGroup(self, group): self.group = group
    def GetParentGroup(self): return self.group


class FakeBridge(NativeBridge):
    def __init__(self):
        self.version = 'fake-10.0'
        self.board = SimpleNamespace(GetFileName=lambda: 'example.kicad_pcb')
        self.leases = []
    def serialize(self, fp): return fp.text
    def children(self, fp): return {}
    def snapshot_board(self, path): path.write_text('(kicad_pcb)', encoding='utf-8')
    def prepare_live(self, plan):
        text = plan.build()
        return plan.owner, FakeFootprint(text), text


class LiveControlFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.model = self.root/'part.step'; self.model.write_bytes(b'opaque model bytes')
        self.original = '(footprint "x" (model "${KIPRJMOD}/part.step" (scale (xyz 1 2 3))))'
        self.planner = Planner(Resolver(self.root))
        self.bridge = FakeBridge()
    def tearDown(self): self.tmp.cleanup()
    def plan(self):
        plan = self.planner.scan(self.original)
        plan.owner = FakeFootprint(self.original)
        return plan
    def test_object_identity_preserved(self):
        plan = self.plan(); owner = plan.owner; group = owner.group
        self.bridge.apply_live([plan], self.root)
        self.assertIs(plan.owner, owner)
        self.assertIs(plan.owner.group, group)
        self.assertEqual(plan.owner.text, plan.build())
    def test_backup_precedes_swap(self):
        plan = self.plan(); original_swap = plan.owner.SwapItemData
        def swap(image):
            self.assertEqual(len(list((self.root/'.embed_3d_plugin-backups').glob('*/before.kicad_pcb'))), 1)
            return original_swap(image)
        plan.owner.SwapItemData = swap
        self.bridge.apply_live([plan], self.root)
    def test_preflight_failure_changes_nothing(self):
        plan = self.plan()
        with patch.object(self.bridge, 'prepare_live', side_effect=ValueError('preflight')):
            with self.assertRaises(ValueError): self.bridge.apply_live([plan], self.root)
        self.assertEqual(plan.owner.text, self.original)
    def test_second_footprint_failure_rolls_first_back(self):
        one, two = self.plan(), self.plan()
        def broken_swap(_): raise RuntimeError('injected second swap failure')
        two.owner.SwapItemData = broken_swap
        with self.assertRaisesRegex(RuntimeError, 'second swap'):
            self.bridge.apply_live([one, two], self.root)
        self.assertEqual(one.owner.text, self.original)
        self.assertEqual(two.owner.text, self.original)
    def test_images_retained_until_action_refresh(self):
        plan = self.plan()
        self.bridge.apply_live([plan], self.root)
        self.assertEqual(len(self.bridge.leases), 1)
        self.assertEqual(self.bridge.leases[0].text, self.original)
    def test_board_file_not_implicitly_saved(self):
        plan = self.plan(); job = self.bridge.apply_live([plan], self.root)
        import json
        self.assertEqual(json.loads((job/'manifest.json').read_text())['status'], 'applied-in-memory-not-saved')


if __name__ == '__main__': unittest.main()
