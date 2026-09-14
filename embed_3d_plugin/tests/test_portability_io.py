"""Filesystem/manifest regression tests; no native KiCad runtime is simulated."""
import json
from pathlib import Path
import tempfile
import unittest
from embed_3d_plugin.portability_io import *


class PortabilityIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'circuit.kicad_pcb';self.source.write_bytes(b'original')
    def tearDown(self):self.tmp.cleanup()
    def plan(self):
        return Extraction({'models/test.step':b'opaque model'},
                 {'kind':'pcb','source':str(self.source),'source_files':{'.':sha256(b'original')}}).finalize()
    def test_extract_preview_no_writes(self):
        self.assertEqual(self.plan().preview()['files'],1)
        self.assertEqual(list(self.root.iterdir()),[self.source])
    def test_publish_readback_and_unchanged_source(self):
        dest=self.root/'my assets';self.plan().publish(dest)
        _,files=load_extraction(dest,self.source)
        self.assertEqual(files['models/test.step'],b'opaque model');self.assertEqual(self.source.read_bytes(),b'original')
    def test_reuse_identical_files(self):
        p=self.plan();dest=self.root/'assets';p.publish(dest);p.publish(dest)
        self.assertEqual(len(list(dest.rglob('*.step'))),1)
    def test_existing_different_file_nothing_changed(self):
        dest=self.root/'assets';dest.mkdir();(dest/'b').write_bytes(b'old')
        with self.assertRaises(ValueError):publish_files(dest,{'a':b'new','b':b'new'})
        self.assertFalse((dest/'a').exists());self.assertEqual((dest/'b').read_bytes(),b'old')
    def test_publication_cancel_rolls_back(self):
        dest=self.root/'assets';calls=[0]
        def stop():calls[0]+=1;return calls[0]>1
        with self.assertRaises(InterruptedError):publish_files(dest,{'a':b'new','sub/b':b'new'},stop)
        self.assertFalse(dest.exists())
    def test_changed_source_invalidates_preview(self):
        p=self.plan();self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Source changed'):p.publish(self.root/'assets')
        self.assertFalse((self.root/'assets').exists())
    def test_modified_asset_blocks_relink_manifest_read(self):
        dest=self.root/'assets';self.plan().publish(dest);(dest/'models/test.step').write_bytes(b'edited')
        with self.assertRaisesRegex(ValueError,'changed'):load_extraction(dest,self.source)
    def test_missing_asset_blocks(self):
        dest=self.root/'assets';self.plan().publish(dest);(dest/'models/test.step').unlink()
        with self.assertRaises(ValueError):load_extraction(dest)
    def test_traversal_absolute_windows_reserved_paths(self):
        for name in ('../escape','/absolute','a//b','a/./b','a/../b','C:/file','a\\b','a/CON.txt','a/name.','nul','x\x00'):
            with self.subTest(name=name),self.assertRaises(ValueError):checked_relative(name)
    def test_unicode_and_spaces(self):
        dest=self.root/'héllo project';publish_files(dest,{'платы/Board with spaces.kicad_mod':b'data'})
        self.assertTrue((dest/'платы/Board with spaces.kicad_mod').is_file())
    def test_casefold_collision_blocked(self):
        with self.assertRaises(ValueError):publish_files(self.root/'assets',{'a.step':b'1','A.STEP':b'2'})
    def test_symlink_target_blocked(self):
        try:
            (self.root/'link').symlink_to(self.root,target_is_directory=True)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege is unavailable')
            raise
        with self.assertRaises(ValueError):publish_files(self.root/'link',{'a':b'new'})
    def test_new_design_no_overwrites_snapshots(self):
        dest=self.root/'design';publish_design(dest,{'a.kicad_pcb':b'after'},{'a.kicad_pcb':b'before'},{'operation':'test'})
        self.assertEqual((dest/'WayriCAD Embed3D-originals/a.kicad_pcb').read_bytes(),b'before')
        with self.assertRaises(ValueError):publish_design(dest,{}, {}, {})
    def test_native_validation_failure_leaves_no_design(self):
        def reject(_):raise ValueError('native rejected')
        with self.assertRaises(ValueError):publish_design(self.root/'out',{'a':b'data'},{},{},validate=reject)
        self.assertFalse((self.root/'out').exists());self.assertFalse(list(self.root.glob('.embed_3d_plugin-design-*')))
    def test_table_collision_and_unrelated_rows(self):
        table=add_table_entry('','symbols','User','${KIPRJMOD}/User.kicad_sym')
        self.assertEqual(add_table_entry(table,'symbols','User','${KIPRJMOD}/User.kicad_sym'),table)
        with self.assertRaises(ValueError):add_table_entry(table,'symbols','User','/different')
        other=add_table_entry(table,'symbols','New','/new.kicad_sym')
        self.assertIn('"User"',other);self.assertIn('"New"',other)
    def test_library_table_rebased_for_copied_project(self):
        old=add_table_entry('','footprints','User','${KIPRJMOD}/lib.pretty').encode()
        files=rebase_library_tables({'fp-lib-table':old},self.root,self.root/'new')
        self.assertIn('${KIPRJMOD}/../lib.pretty',files['fp-lib-table'].decode())
    def test_relative_and_absolute_references(self):
        self.assertEqual(file_reference(self.root/'assets/x.step',self.root/'out'),'${KIPRJMOD}/../assets/x.step')
        self.assertEqual(file_reference(self.root/'assets/x.step',self.root/'out','absolute'),(self.root/'assets/x.step').as_posix())
    def test_reserved_snapshot_output_refused(self):
        with self.assertRaises(ValueError):publish_design(self.root/'out',{'WayriCAD Embed3D-originals/a':b'bad'}, {},{})
