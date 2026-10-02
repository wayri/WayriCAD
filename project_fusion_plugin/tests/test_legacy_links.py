import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_legacy_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
restore=importlib.import_module(PACKAGE+'.legacy_sources').restore_source_backup
legacy=importlib.import_module(PACKAGE+'.legacy_links')
model=importlib.import_module(PACKAGE+'.model')
sx=importlib.import_module(PACKAGE+'.sexpr')

class ArchiveTests(unittest.TestCase):
    def archive(self,base,wrong_hash=False,unsafe=False,missing_child=False):
        original=base/'original';project=original/'board.kicad_pro'
        content={project:b'{}',project.with_suffix('.kicad_sch'):b'(kicad_sch (uuid "root") (sheet (property "Sheetfile" "child.kicad_sch")))'}
        if not missing_child:content[original/'child.kicad_sch']=b'(kicad_sch (uuid "child"))'
        archive=base/'source.zip';manifest=[]
        with zipfile.ZipFile(archive,'w') as package:
            for index,(path,data) in enumerate(content.items()):
                member=f'Module/{index}_{path.name}';package.writestr(member,data)
                manifest.append({'source':'Module','original_path':str(path),'archive_member':member,'sha256':('0'*64 if wrong_hash else hashlib.sha256(data).hexdigest())})
            package.writestr('manifest.json',json.dumps(manifest))
            if unsafe:package.writestr('../escape',b'x')
        return archive,project

    def test_verified_reconstruction_preserves_ids_and_dependency_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);archive,project=self.archive(base)
            value=restore(archive,'Module',base/'restored')
            self.assertEqual(value['original_project'],str(project))
            tree=sx.load(Path(value['spec'].project).with_suffix('.kicad_sch'))
            self.assertEqual(sx.value(tree,'uuid'),'root')
            self.assertEqual(len(value['original_filehashes']),3)
            self.assertTrue((base/'restored/child.kicad_sch').is_file())

    def test_bad_hash_traversal_and_missing_dependency_are_refused(self):
        for argument,reason in [('wrong_hash','hash mismatch'),('unsafe','Unsafe'),('missing_child','lacks a referenced')]:
            with self.subTest(argument=argument),tempfile.TemporaryDirectory() as folder:
                base=Path(folder);archive,_=self.archive(base,**{argument:True})
                with self.assertRaisesRegex(model.MergeError,reason):restore(archive,'Module',base/'restored')
                self.assertFalse((base/'restored').exists())

    def test_only_page_allocation_is_ignored_in_sheet_proof(self):
        a=sx.loads('(kicad_sch (uuid "root") (instances (path "x" (page "1"))) (symbol (at 1 2)))')
        b=sx.loads('(kicad_sch (uuid "root") (instances (path "x" (page "9"))) (symbol (at 1 2)))')
        self.assertEqual(legacy._sheet_content(a),legacy._sheet_content(b))
        sx.child(sx.children(b,'symbol')[0],'at')[1]='3'
        self.assertNotEqual(legacy._sheet_content(a),legacy._sheet_content(b))


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_LINKED')=='1','Native KiCad legacy adoption opt-in')
class NativeAdoptionTests(unittest.TestCase):
    def test_pristine_legacy_is_adopted_and_edited_import_is_refused(self):
        from test_sections_native import make_fixture
        insertion=importlib.import_module(PACKAGE+'.insertion');linked=importlib.import_module(PACKAGE+'.linked_updates')
        with tempfile.TemporaryDirectory(prefix='fusion-legacy-native-') as folder:
            base=Path(folder);target,_=make_fixture(base/'target');source,_=make_fixture(base/'source');source.alias='Unit1'
            insertion.apply_import(insertion.preview_import(target.project,[source],False,base/'insert'))
            manifest=base/'target'/linked.MANIFEST;manifest.unlink()
            proposal=linked.scan_links(target.project)['legacy_candidates'][0]
            self.assertTrue(proposal['verified'],proposal)
            tree=sx.load(base/'target/child.kicad_sch');before=(base/'target/board.kicad_sch').read_bytes();pcb=(base/'target/board.kicad_pcb').read_bytes()
            plan=linked.preview_adopt_links(target.project,[proposal['id']],base/'adopt');insertion.apply_import(json.loads(json.dumps(plan)))
            self.assertEqual((base/'target/board.kicad_sch').read_bytes(),before);self.assertEqual((base/'target/board.kicad_pcb').read_bytes(),pcb)
            self.assertEqual(linked.scan_links(target.project)['links'][0]['status'],'current')
            data=json.loads(manifest.read_text(encoding='utf-8'));sheet=base/'target'/data['links'][0]['sheet_files'][-1]
            changed=sx.load(sheet);sx.prop(sx.children(changed,'symbol')[0],'Value')[2]=sx.q('47k');sx.save(sheet,changed);manifest.unlink()
            rejected=linked.scan_links(target.project)['legacy_candidates'][0]
            self.assertFalse(rejected['verified'])
            with self.assertRaises(model.MergeError):linked.preview_adopt_links(target.project,[rejected['id']],base/'rejected')

if __name__=='__main__':unittest.main()
