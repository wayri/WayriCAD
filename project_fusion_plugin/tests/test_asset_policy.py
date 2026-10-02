import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('fusion_asset_policy_test')
package.__path__ = [str(ROOT)]
sys.modules.setdefault(package.__name__, package)

from fusion_asset_policy_test.assets import Collector, audit_assets
from fusion_asset_policy_test.model import MergeError, SourceSpec
from fusion_asset_policy_test import sexpr as sx


class AssetPolicyTests(unittest.TestCase):
    def source(self, root):
        return types.SimpleNamespace(
            alias='Source', spec=SourceSpec(str(root/'Source.kicad_pro'), 'Source'),
            project_file=root/'Source.kicad_pro', project={}, asset_manifest=[],
            hashes={}, files=set(), fp_lib_map={}, fp_id_map={}, layer_map={})

    def test_model_reference_is_copied_or_external_with_source_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            model=root/'body.step'; model.write_bytes(b'solid body')
            for copy_assets in (True, False):
                output=root/('copied' if copy_assets else 'external'); output.mkdir()
                source=self.source(root)
                collector=Collector(source,output,lambda _:None,copy_assets=copy_assets)
                tree=['footprint',['model',sx.q('${KIPRJMOD}/body.step')]]
                collector.rewrite_tree(tree,root)
                emitted=str(tree[1][1])
                self.assertEqual(emitted.startswith('${KIPRJMOD}/'),copy_assets)
                if not copy_assets:
                    self.assertEqual(emitted,model.resolve().as_posix())
                    self.assertEqual(source.asset_manifest[0]['source_path'],emitted)
                    self.assertTrue(source.asset_manifest[0]['external'])
                audit=audit_assets([source],output)
                self.assertEqual(audit['self_contained'],copy_assets)
                self.assertEqual(source.hashes[str(model.resolve())],source.asset_manifest[0]['sha256'])

    def test_external_footprint_library_table_and_hash_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'out'; output.mkdir()
            library=root/'components.pretty'; library.mkdir()
            member=library/'Resistor.kicad_mod'
            member.write_text('(footprint "Resistor" (layer "F.Cu"))',encoding='utf-8')
            source=self.source(root)
            collector=Collector(source,output,lambda _:None,copy_assets=False)
            table=['fp_lib_table',['version','7']]
            collector.footprint_library('Parts',library,True,{'Resistor'},table)
            entry=sx.children(table,'lib')[0]
            self.assertEqual(sx.value(entry,'uri'),library.resolve().as_posix())
            self.assertEqual(source.fp_id_map['Parts:Resistor'].split(':')[-1],'Resistor')
            self.assertFalse((output/'libraries').exists())
            self.assertEqual(audit_assets([source],output)['generated_count'],0)
            member.write_text('(footprint "changed")',encoding='utf-8')
            with self.assertRaisesRegex(MergeError,'External dependency changed'):
                audit_assets([source],output)

    def test_missing_required_model_still_blocks_external_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            collector=Collector(self.source(root),root/'out',lambda _:None,
                                strict=True,copy_assets=False)
            with self.assertRaisesRegex(MergeError,'unresolved 3D model'):
                collector.link('missing.step',root,'3D model')

    def test_auxiliary_file_still_copies_when_library_copy_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'out'
            datasheet=root/'part.pdf'; datasheet.write_bytes(b'%PDF-1.4')
            source=self.source(root)
            collector=Collector(source,output,lambda _:None,copy_assets=False)
            uri=collector.link('part.pdf',root,'field Datasheet')
            self.assertTrue(uri.startswith('${KIPRJMOD}/'))
            self.assertTrue((output/uri.removeprefix('${KIPRJMOD}/')).is_file())
            self.assertTrue(audit_assets([source],output)['self_contained'])

    def test_symbol_library_remains_external_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'out'; output.mkdir()
            library=root/'Parts.kicad_sym'
            original='(kicad_symbol_lib (version 20231120) (generator "eeschema") (symbol "R"))'
            library.write_text(original,encoding='utf-8')
            source=self.source(root)
            collector=Collector(source,output,lambda _:None,copy_assets=False)
            table=['sym_lib_table',['version','7']]
            collector.symbol_library('Parts',library,table)
            self.assertEqual(sx.value(sx.children(table,'lib')[0],'uri'),library.resolve().as_posix())
            self.assertFalse((output/'libraries').exists())
            self.assertEqual(library.read_text(encoding='utf-8'),original)
            self.assertFalse(audit_assets([source],output)['self_contained'])

    def test_relative_footprint_model_requires_generated_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'out'; output.mkdir()
            library=root/'Parts.pretty'; library.mkdir()
            model=root/'body.step'; model.write_bytes(b'solid body')
            member=library/'R.kicad_mod'
            member.write_text('(footprint "R" (layer "F.Cu") (model "../body.step"))',encoding='utf-8')
            source=self.source(root)
            collector=Collector(source,output,lambda _:None,copy_assets=False)
            table=['fp_lib_table',['version','7']]
            collector.footprint_library('Parts',library,True,{'R'},table)
            uri=sx.value(sx.children(table,'lib')[0],'uri')
            self.assertTrue(uri.startswith('${KIPRJMOD}/'))
            generated=list((output/'libraries').rglob('R.kicad_mod'))
            self.assertEqual(len(generated),1)
            self.assertIn(model.resolve().as_posix(),generated[0].read_text(encoding='utf-8'))
            self.assertTrue(any(r['status']=='generated-repair' for r in source.asset_manifest))
            self.assertTrue(any(r['status']=='external' and r['source_path']==model.resolve().as_posix()
                                for r in source.asset_manifest))
            self.assertEqual(audit_assets([source],output)['generated_count'],1)


if __name__=='__main__':
    unittest.main()
