"""Independent checkbox extraction must preserve native library path context."""
import test_workspace as workspace_fixture
from embed_3d_plugin import workspace as w
from embed_3d_plugin import board_package as bp
from embed_3d_plugin.codec import sha256
from embed_3d_plugin.sexpr import parse, quote
from pathlib import Path
import unittest

class LibraryContextTests(unittest.TestCase):
    def setUp(self):
        # Reuse the fixture only, not the parent test suite.
        self.fixture=workspace_fixture.WorkspaceTests();self.fixture.setUp()
        self.root=self.fixture.root;self.pcb=self.fixture.pcb;self.uid=self.fixture.uid
        self.library=self.root/'Custom.pretty';self.library.mkdir()
        (self.library/'own.step').write_bytes(b'opaque custom model')
        (self.root/'fp-lib-table').write_text('(fp_lib_table (version 7) (lib (name "Lib") (type "KiCad") (uri "${KIPRJMOD}/Custom.pretty") (options "") (descr "")))')
        old=quote(str(self.fixture.model))
        self.assertIn(old, self.pcb.read_text())
        self.pcb.write_text(self.pcb.read_text().replace(old,quote('own.step')))
        self.norm={uid:(name,raw.replace(old,quote('own.step'))) for uid,(name,raw) in self.fixture.norm.items()}
        self.inv=w.scan_design(self.pcb)
    def tearDown(self):self.fixture.tearDown()
    def test_collect_external_from_original_library_not_project(self):
        opt=w.Options(self.root/'assets',self.root/'out',include_external=True)
        sel=w.Selection(footprints={self.uid},models={self.uid})
        plan=w.prepare_operation(self.inv,sel,'unbundle',opt,normalized=self.norm,normalized_hash=sha256(self.pcb.read_bytes()))
        item=next(iter(plan.extractions.values()))
        self.assertIn(b'opaque custom model',item.files.values())
        raw=next(data.decode() for name,data in item.files.items() if name.endswith('.kicad_mod'))
        self.assertTrue(bp.model_refs(raw)[0].startswith(opt.assets.as_posix()))
    def test_footprint_only_keeps_original_external_target_without_copy(self):
        opt=w.Options(self.root/'assets',self.root/'out')
        plan=w.prepare_operation(self.inv,w.Selection(footprints={self.uid}),'unbundle',opt,normalized=self.norm,normalized_hash=sha256(self.pcb.read_bytes()))
        item=next(iter(plan.extractions.values()))
        self.assertFalse(any(name.endswith('.step') for name in item.files))
        raw=next(data.decode() for name,data in item.files.items() if name.endswith('.kicad_mod'))
        self.assertEqual(bp.model_refs(raw),[(self.library/'own.step').resolve().as_posix()])
    def test_combined_uses_library_context_and_preserves_transforms(self):
        opt=w.Options(self.root/'assets',self.root/'out',include_external=True)
        plan=w.prepare_operation(self.inv,w.Selection(footprints={self.uid},models={self.uid}),'unbundle-relink',opt,normalized=self.norm,normalized_hash=sha256(self.pcb.read_bytes()))
        plan.apply()
        source=self.pcb.read_text();result=(opt.output/self.pcb.name).read_text()
        self.assertEqual(bp.model_settings(parse(source).nodes(source,'footprint')[0].raw(source)),bp.model_settings(parse(result).nodes(result,'footprint')[0].raw(result)))
