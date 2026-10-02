import sys
import types
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('fusion_assets_test');package.__path__=[str(ROOT)]
sys.modules.setdefault(package.__name__,package)
from fusion_assets_test.assets import Collector
from fusion_assets_test.model import SourceSpec,MergeError
from fusion_assets_test import sexpr as sx

class AssetTests(unittest.TestCase):
    def source(self,root):
        return types.SimpleNamespace(alias='Example',spec=SourceSpec(str(root/'Example.kicad_pro'),'Example'),project_file=root/'Example.kicad_pro',
                                     project={},asset_manifest=[],hashes={},files=set(),fp_lib_map={},fp_id_map={},layer_map={})

    def test_part_number_datasheet_is_text_but_pdf_required(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);c=Collector(self.source(root),root/'out',lambda _:None,strict=True)
            tree=['symbol',['property',sx.q('Datasheet'),sx.q('ABC-123')]]
            c.rewrite_tree(tree,root)
            self.assertEqual(tree[1][2],'ABC-123')
            tree[1][2]=sx.q('missing.pdf')
            with self.assertRaises(MergeError):c.rewrite_tree(tree,root)

    def test_registered_native_folder_need_not_end_pretty(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);library=root/'vendor'/'KiCad';library.mkdir(parents=True)
            (library/'R.kicad_mod').write_text('(footprint "R" (layer "F.Cu"))')
            c=Collector(self.source(root),root/'out',lambda _:None,strict=True)
            table=['fp_lib_table']
            c.footprint_library('Vendor',library,False,{'R'},table)
            self.assertTrue(c.source.fp_id_map['Vendor:R'].endswith(':R'))
            self.assertEqual(len(list((root/'out').rglob('R.kicad_mod'))),1)

if __name__=='__main__':unittest.main()
