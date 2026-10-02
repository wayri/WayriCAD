import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_fusion_sections_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
s=importlib.import_module(PACKAGE+'.sections')
sx=importlib.import_module(PACKAGE+'.sexpr')
model=importlib.import_module(PACKAGE+'.model')
sch=importlib.import_module(PACKAGE+'.schematic')

class SectionTests(unittest.TestCase):
    def fixture(self,root):
        rid='11111111-1111-4111-8111-111111111111'; child='22222222-2222-4222-8222-222222222222'
        other='33333333-3333-4333-8333-333333333333'; uid='44444444-4444-4444-8444-444444444444'
        (root/'board.kicad_pro').write_text('{}')
        (root/'board.kicad_pcb').write_text('(kicad_pcb (version 20260306))')
        (root/'board.kicad_sch').write_text(f'''(kicad_sch (version 20260306) (uuid "{rid}")
        (sheet (uuid "{child}") (property "Sheetname" "One") (property "Sheetfile" "child.kicad_sch"))
        (sheet (uuid "{other}") (property "Sheetname" "Two") (property "Sheetfile" "child.kicad_sch")))''')
        (root/'child.kicad_sch').write_text(f'''(kicad_sch (version 20260306) (uuid "55555555-5555-4555-8555-555555555555")
        (lib_symbols (symbol "Device:R")) (symbol (lib_id "Device:R") (uuid "{uid}") (unit 1)
        (property "Reference" "R1") (property "Value" "10k") (property "Footprint" "R:0603")
        (instances (project "board" (path "/{rid}/{child}" (reference "R1") (unit 1))
        (path "/{rid}/{other}" (reference "R2") (unit 1))))))''')
        return model.SourceSpec(str(root/'board.kicad_pro'),'A',variant='<Default>'),'/'+rid+'/'+child

    def test_exact_instances_not_filenames(self):
        with tempfile.TemporaryDirectory() as folder:
            spec,path=self.fixture(Path(folder)); metadata=s.list_sections(spec)
            self.assertEqual(len(metadata),2)
            self.assertEqual(metadata[0]['sheet_path'],path)
            self.assertNotEqual(metadata[0]['sheet_path'],metadata[1]['sheet_path'])
            self.assertEqual(metadata[0]['file'],metadata[1]['file'])

    def test_occurrence_clone_rebases_only_owning_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,path=self.fixture(root); source=sch.discover(spec,sch.new_uuid())
            output=root/'output';output.mkdir()
            paths=s._write_hierarchy(source,source.sheets[1],output,'section')
            tree=sx.load(output/'section.kicad_sch');symbol=sx.children(tree,'symbol')[0]
            projects=sx.children(sx.child(symbol,'instances'),'project')
            self.assertEqual(len(projects),1);self.assertEqual(projects[0][1],'section')
            instance=sx.child(projects[0],'path')
            self.assertEqual(instance[1],paths[path]);self.assertEqual(sx.value(instance,'reference'),'R1')
            self.assertNotIn('R2',sx.dumps(tree))

    def test_region_refuses_contact_and_partial_geometry(self):
        region=s._region([0,0,10,10])
        self.assertEqual(s._relation([1,1,9,9],region),'inside')
        self.assertEqual(s._relation([0,1,9,9],region),'boundary')
        self.assertEqual(s._relation([-2,1,5,9],region),'boundary')
        self.assertEqual(s._relation([-2,-2,-1,-1],region),'outside')
        for value in ([0,0,0,1],[0,0,float('nan'),1],[0,1,2],[-10001,0,2,2]):
            with self.assertRaises(model.MergeError):s._region(value)

    def test_partitions_detect_outside_parent_bridge(self):
        full=SimpleNamespace(nets={'GND':{('R1','1'),('R2','1'),('J1','1')}})
        split=SimpleNamespace(nets={'A':{('R1','1')},'B':{('R2','1')}})
        joined=SimpleNamespace(nets={'Local':{('R1','1'),('R2','1')}})
        self.assertNotEqual(set(s._partitions(full,{'R1','R2'})),set(s._partitions(split,{'R1','R2'})))
        self.assertEqual(set(s._partitions(full,{'R1','R2'})),set(s._partitions(joined,{'R1','R2'})))

    def test_geometry_signature_tracks_width_position_and_pads(self):
        a=sx.loads('(segment (start 1 2) (end 3 4) (width 0.2) (layer "F.Cu") (net 1))')
        b=sx.loads('(segment (start 1.000 2.0) (end 3 4) (width 0.200) (layer "F.Cu") (net 2))')
        self.assertEqual(s._geometry_signature(a),s._geometry_signature(b))
        sx.put(b,'width','0.3');self.assertNotEqual(s._geometry_signature(a),s._geometry_signature(b))

    def test_apply_refuses_stale_existing_or_nested_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,path=self.fixture(root)
            plan={'spec':model.asdict(spec),'sheet_path':path,'region_mm':[0,0,10,10],'cli_path':'','hashes':s.fingerprint(root)}
            with self.assertRaises(model.MergeError):s.apply_section(plan,root/'nested')
            existing=root.parent/(root.name+'-existing');existing.mkdir()
            try:
                with self.assertRaises(model.MergeError):s.apply_section(plan,existing)
            finally:existing.rmdir()
            (root/'changed').write_text('changed')
            with self.assertRaises(model.MergeError):s.apply_section(plan,root.parent/(root.name+'-candidate'))

    def test_apply_rolls_back_native_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'source';root.mkdir();spec,path=self.fixture(root)
            plan={'spec':model.asdict(spec),'sheet_path':path,'region_mm':[0,0,10,10],'cli_path':'','hashes':s.fingerprint(root)}
            with mock.patch.object(s,'_build',side_effect=model.MergeError('Native validation rejected')):
                with self.assertRaises(model.MergeError):s.apply_section(plan,base/'candidate')
            self.assertFalse((base/'candidate').exists())
            self.assertEqual(s.fingerprint(root),plan['hashes'])
            self.assertEqual(sorted(p.name for p in base.iterdir()),['source'])

if __name__=='__main__':unittest.main()
