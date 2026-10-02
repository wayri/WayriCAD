import csv
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock

# Import source modules without executing SWIG ActionPlugin registration.
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_fusion_fields_test'
pkg = ModuleType(PACKAGE); pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg
b = importlib.import_module(PACKAGE + '.bom_fields')
sx = importlib.import_module(PACKAGE + '.sexpr')
model = importlib.import_module(PACKAGE + '.model')
schematic = importlib.import_module(PACKAGE + '.schematic')

def row(path='/root/a', ref='R1', unit=1, **fields):
    return dict(identity=('A',path,path.split('/')[-1]), source='A', variant='EM',
                reference=ref, unit=unit, sheet_path='/root',
                fields={'Reference':ref,'Value':'10k','Footprint':'R:0402',**fields},
                flags=dict(b.FLAGS))

class FieldsTests(unittest.TestCase):
    def test_groups_units_and_keeps_differences(self):
        first=row('/root/a',unit=1,MPN='X'); second=row('/root/b',unit=2,MPN='X')
        other=row('/root/c',ref='R2',MPN='Y')
        dnp=row('/root/d',ref='R3',MPN='X'); dnp['flags']['dnp']='yes'
        excluded=row('/root/e',ref='R4'); excluded['flags']['in_bom']='no'
        groups=b.grouped_bom([first,second,other,dnp,excluded])
        self.assertEqual(sorted(g['quantity'] for g in groups),[1,1,1])
        self.assertEqual(sum(len(g['identities']) for g in groups),4)
        self.assertEqual(len(b.grouped_bom([excluded],True)),1)
        second['fields']['MPN']='conflict'
        with self.assertRaises(model.MergeError): b.grouped_bom([first,second])

    def test_reused_reference_different_occurrence(self):
        a=row(); c=row('/root/s2/a'); c['sheet_path']='/root/s2'
        self.assertEqual(b.grouped_bom([a,c])[0]['quantity'],2)

    def test_preview_conflicts_and_structural_refusal(self):
        r=row(MPN='A',Manufacturer='B')
        p=b.preview_fields([r],[r['identity']],{'Value':'22k'},{'MPN':'Part Number'})
        self.assertEqual(r['fields']['Value'],'10k')
        self.assertEqual(p[0]['after']['Part Number'],'A')
        for edit in ({'Footprint':'x'}, {'Reference':'X'}, {'dnp':'yes'}):
            with self.assertRaises(model.MergeError): b.preview_fields([r],[r['identity']],edit)
        for edit in ({'footprint':'x'}, {'DNP':'yes'}, {'reference':'X'}, {'Value':'1','value':'2'}):
            with self.assertRaises(model.MergeError): b.preview_fields([r],[r['identity']],edit)
        with self.assertRaises(model.MergeError):
            b.preview_fields([r],[r['identity']],renames={'MPN':'footprint'})
        with self.assertRaises(model.MergeError):
            b.grouped_bom([row(footprint='duplicate')])
        with self.assertRaises(model.MergeError):
            b.preview_fields([r],[r['identity']],renames={'MPN':'Manufacturer'})
        with self.assertRaises(model.MergeError): b.preview_fields([r],[('missing','a','b')],{})

    def test_csv_roundtrip(self):
        r=row(Notes='µ, "quoted"\nsecond line')
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'fields.csv'; b.export_csv(target,[r])
            with target.open(encoding='utf-8-sig',newline='') as stream:
                data=list(csv.DictReader(stream))
            self.assertEqual(data[0]['Notes'],r['fields']['Notes'])

    def fixture(self, folder):
        root='11111111-1111-4111-8111-111111111111'
        symbol='22222222-2222-4222-8222-222222222222'
        pro=folder/'board.kicad_pro'
        pro.write_text(json.dumps({'schematic':{'variants':[{'name':'EM'}]}}))
        pro.with_suffix('.kicad_pcb').write_text('(kicad_pcb (version 20260306))')
        pro.with_suffix('.kicad_sch').write_text(f'''(kicad_sch (version 20260306) (uuid "{root}")
          (lib_symbols (symbol "Device:R"))
          (symbol (lib_id "Device:R") (uuid "{symbol}") (unit 1)
          (property "Reference" "R1") (property "Value" "10k") (property "Footprint" "R:0402")
          (instances (project "board" (path "/{root}" (reference "R1") (unit 1)
             (variant (name "EM") (field (name "Value") (value "22k"))))))))''')
        return schematic.discover(model.SourceSpec(str(pro),'A',variant='EM'),schematic.new_uuid())

    def test_variant_inventory_and_copy_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'source'; folder.mkdir(); source=self.fixture(folder)
            original=source.schematic_file.read_bytes()
            rows=b.inventory([source]); self.assertEqual(rows[0]['fields']['Value'],'22k')
            plan=b.preview_fields(rows,[rows[0]['identity']],{'Value':'47k'},{})
            specs=b.apply_to_copies([source],plan,Path(tmp)/'candidate')
            self.assertEqual(source.schematic_file.read_bytes(),original)
            self.assertEqual(specs[0].variant,b.DEFAULT)
            new=schematic.discover(specs[0],schematic.new_uuid())
            self.assertEqual(b.inventory([new])[0]['fields']['Value'],'47k')
            with self.assertRaises(model.MergeError): b.apply_to_copies([source],plan,Path(tmp)/'candidate')

    def test_stale_refusal_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'source'; folder.mkdir(); source=self.fixture(folder)
            rows=b.inventory([source]); plan=b.preview_fields(rows,[rows[0]['identity']],{'Value':'47k'})
            source.schematic_file.write_text(source.schematic_file.read_text()+'\n')
            target=Path(tmp)/'candidate'
            with self.assertRaises(model.MergeError): b.apply_to_copies([source],plan,target)
            self.assertFalse(target.exists())

    def test_publication_failure_rolls_back_and_options_survive(self):
        engine=importlib.import_module(PACKAGE+'.engine')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'source'; folder.mkdir(); source=self.fixture(folder)
            source.spec.path_variables={'MODELS':'C:/Models'}
            source.spec.path_remaps={'C:/Old':'C:/New'}
            source.spec.extra_asset_paths=['C:/Auxiliary']
            original=source.schematic_file.read_bytes()
            target=Path(tmp)/'candidate'
            with mock.patch.object(engine,'publish',side_effect=OSError('injected publish failure')):
                with self.assertRaises(OSError): b.apply_to_copies([source],[],target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).glob('.fusion-fields-*')),[])
            specs=b.apply_to_copies([source],[],target)
            self.assertEqual(specs[0].path_variables,source.spec.path_variables)
            self.assertEqual(specs[0].path_remaps,source.spec.path_remaps)
            self.assertEqual(specs[0].extra_asset_paths,source.spec.extra_asset_paths)
            self.assertEqual(source.schematic_file.read_bytes(),original)

    def test_local_assets_copied_and_external_sheets_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'source'; folder.mkdir(); source=self.fixture(folder)
            (folder/'Models').mkdir(); (folder/'Models'/'part.step').write_bytes(b'local model fixture')
            (folder/'Local.pretty').mkdir(); (folder/'Local.pretty'/'R.kicad_mod').write_text('(footprint "R")')
            (folder/'fp-lib-table').write_text('(fp_lib_table (lib (name "Local") (type "KiCad") (uri "${KIPRJMOD}/Local.pretty")))')
            source.project['schematic']['variant']='EM'; source.project['schematic']['current_variant']='EM'
            source.project_file.write_text(json.dumps(source.project))
            source.hashes[str(source.project_file)]=hashlib.sha256(source.project_file.read_bytes()).hexdigest()
            target=Path(tmp)/'candidate'
            b.apply_to_copies([source],[],target)
            self.assertEqual((target/'A'/'Models'/'part.step').read_bytes(),b'local model fixture')
            self.assertTrue((target/'A'/'Local.pretty'/'R.kicad_mod').is_file())
            self.assertEqual((target/'A'/'fp-lib-table').read_bytes(),(folder/'fp-lib-table').read_bytes())
            compiled=json.loads((target/'A'/'board.kicad_pro').read_text())['schematic']
            self.assertNotIn('variant',compiled); self.assertNotIn('current_variant',compiled)
            source.sheets[0].source_path=Path(tmp)/'external.kicad_sch'
            with self.assertRaisesRegex(model.MergeError,'external child'):
                b.apply_to_copies([source],[],Path(tmp)/'external_candidate')

if __name__=='__main__': unittest.main()
