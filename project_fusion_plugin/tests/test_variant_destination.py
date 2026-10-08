"""Native destination variants retain imported Default and target states."""
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType,SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
PACKAGE='_fusion_variant_destination_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
m=importlib.import_module(PACKAGE+'.model')
v=importlib.import_module(PACKAGE+'.variants')
sx=importlib.import_module(PACKAGE+'.sexpr')
sch=importlib.import_module(PACKAGE+'.schematic')
engine=importlib.import_module(PACKAGE+'.engine')
sections=importlib.import_module(PACKAGE+'.sections')
insert=importlib.import_module(PACKAGE+'.insertion')

class DestinationTests(unittest.TestCase):
    def source(self,mode,name):
        return SimpleNamespace(spec=m.SourceSpec('board.kicad_pro','Incoming',variant='Build',variant_mode=mode,destination_variant=name),alias='Incoming')

    def test_metadata_preserves_existing_and_checks_names(self):
        original={'schematic':{'variants':[{'name':'Working','description':'Keep'}],'current_variant':'Working'}}
        before=copy.deepcopy(original)
        result=v.destination_metadata(original,[self.source('merge','Working'),self.source('separate','Imported')],True)
        self.assertEqual(original,before)
        self.assertEqual(result['schematic']['variants'],[{'name':'Working','description':'Keep'},{'name':'Imported'}])
        for mode,name in [('merge','Missing'),('separate','Working'),('separate','<Default>'),('bad','Working')]:
            with self.subTest(mode=mode,name=name),self.assertRaises(m.MergeError):
                v.destination_metadata(original,[self.source(mode,name)],True)

    def test_new_project_resolves_created_name_order_independently(self):
        result=v.destination_metadata({},[self.source('merge','Build'),self.source('separate','Build')])
        self.assertEqual(v.project_names(result),['Build'])

    def test_default_mode_and_setup_roundtrip(self):
        legacy=m.SourceSpec('board.kicad_pro','Incoming')
        self.assertEqual(legacy.variant_mode,'base')
        chosen=self.source('separate','Imported').spec
        opts=m.Options([chosen],'C:/Projects/New',saved_sources_confirmed=True,acknowledge_outline_change=True)
        opts.validate()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'setup.json';path.write_text(json.dumps(opts.to_dict()))
            self.assertEqual(m.Options.from_json(path).to_dict(),opts.to_dict())

    def test_selected_state_survives_rebased_native_instance(self):
        node=sx.loads('''(symbol (uuid "old") (property "Reference" "R1") (property "Value" "10k")
            (property "Footprint" "Resistor:R")
            (instances (project "board" (path "/oldroot" (reference "R1") (unit 1)
              (variant (name "Build") (dnp yes) (field (name "Value") (value "22k")))))))''')
        sheet=SimpleNamespace(tree=['kicad_sch',['version','20260306'],node],old_path='/oldroot',new_path='/newroot/wrapper',
                              source_path=Path('board.kicad_sch'),sub_sheets=[],relative_file='import.kicad_sch',ids={'old':'new'})
        source=self.source('separate','Imported');source.project={'schematic':{'variants':[{'name':'Build'}]}}
        source.project_file=Path('board.kicad_pro');source.sheets=[sheet];source.ref_map={'R1':'R2'}
        v.apply_selected(source)
        self.assertEqual(sx.propval(node,'Value'),'10k');self.assertEqual(sx.value(node,'dnp','no'),'no')
        sx.put(node,'uuid',sx.q('new'));sx.put(node,'instances',['project',sx.q('Combined'),
              ['path',sx.q(sheet.new_path),['reference',sx.q('R2')],['unit','1']]])
        with tempfile.TemporaryDirectory() as folder:
            sx.save(Path(folder)/sheet.relative_file,sheet.tree)
            v.attach_destination(source,folder,'Combined')
            final=sx.children(sx.load(Path(folder)/sheet.relative_file),'symbol')[0]
            effective=v.effective(final,v.object_paths(final,sheet.new_path,'Combined')[0],'Imported',20260306)
            self.assertEqual(effective['fields']['Value'],'22k');self.assertEqual(effective['flags']['dnp'],'yes')
            self.assertEqual(sx.propval(final,'Value'),'10k')

    def test_unknown_source_variant_and_structural_override_refused(self):
        source=self.source('separate','Imported');source.project={'schematic':{'variants':[]}};source.sheets=[]
        with self.assertRaises(m.MergeError):v.select_variant(source)
        node=sx.loads('(symbol (property "Reference" "R1") (property "Footprint" "A"))')
        block=sx.loads('(path "/root" (variant (name "Build") (field (name "Reference") (value "R2"))))')
        with self.assertRaises(m.MergeError):v.effective(node,block,'Build',20260306)

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_VARIANT_DESTINATION')=='1','Opt-in native KiCad variant import')
class NativeDestinationTests(unittest.TestCase):
    def fixture(self,root):
        sys.path.insert(0,str(ROOT/'tests'))
        fixture=importlib.import_module('test_sections_native')
        spec,path=fixture.make_fixture(root)
        for file in ('board.kicad_sch','child.kicad_sch'):
            tree=sx.load(root/file);sx.put(tree,'version','20260306')
            if file=='child.kicad_sch':
                node=sx.children(tree,'symbol')[0]
                entry=v.object_paths(node,path,'board')[0]
                entry.append(sx.loads('(variant (name "Build") (dnp yes) (field (name "Value") (value "22k")))'))
            sx.save(root/file,tree)
        (root/'board.kicad_pro').write_text(json.dumps({'schematic':{'variants':[{'name':'Build'}]}}))
        return m.SourceSpec(spec.project,'Incoming',variant='Build',variant_mode='separate',destination_variant='Imported'),path

    def check_states(self,project,name):
        source=sch.discover(m.SourceSpec(str(project),'Check',variant='<Default>'),sch.new_uuid(),require_board=False)
        imported=[r for r in source.symbols if r.old_ref!='R1'] or source.symbols
        self.assertEqual(sx.propval(imported[0].node,'Value'),'10k')
        source=sch.discover(m.SourceSpec(str(project),'Check',variant=name),sch.new_uuid(),require_board=False)
        imported=[r for r in source.symbols if r.old_ref!='R1'] or source.symbols
        self.assertEqual(sx.propval(imported[0].node,'Value'),'22k')
        self.assertEqual(sx.value(imported[0].node,'dnp'),'yes')
        cli=importlib.import_module(PACKAGE+'.netlist').KiCadCLI()
        output=project.parent/'selected-variant-bom.csv'
        cli.run(['sch','export','bom','--variant',name,'--fields','Reference,Value,DNP','--labels','Reference,Value,DNP',
                 '--output',output,project.with_suffix('.kicad_sch')],cwd=project.parent)
        import csv
        with output.open(encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        matching=[row for row in rows if row['Reference']==imported[0].old_ref]
        self.assertEqual(matching[0]['Value'],'22k')
        self.assertIn(matching[0]['DNP'].lower(),{'yes','true','dnp','1'})

    def test_schematic_subsheet_retains_default_and_selected_native_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,path=self.fixture(root/'source')
            before=sections.fingerprint(root/'source')
            plan=sections.preview_schematic_sections(spec,[path])
            extracted=sections.apply_schematic_sections(plan,root/'section')[0]
            self.assertEqual(extracted.variant_mode,'separate')
            source=sch.discover(extracted,sch.new_uuid(),require_board=False)
            self.assertEqual(sx.propval(source.symbols[0].node,'Value'),'10k')
            self.assertEqual(next(iter(source.destination_states.values()))['fields']['Value'],'22k')
            self.assertEqual(before,sections.fingerprint(root/'source'))
            spec.project=extracted.project
            target,_=self.fixture(root/'target')
            target_project=Path(target.project)
            output=insert.preview_import(target_project,[spec],False,root/'candidate')
            self.check_states(root/'candidate'/target_project.name,'Imported')
            self.assertEqual(output['report']['sources'][0]['variant_handling']['mode'],'separate')

    def test_existing_merge_and_new_project_layout_preserve_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,_=self.fixture(root/'source');target,_=self.fixture(root/'target')
            spec.variant_mode='merge';spec.destination_variant='Build'
            plan=insert.preview_import(target.project,[spec],True,root/'candidate')
            self.check_states(root/'candidate'/'board.kicad_pro','Build')
            self.assertTrue(plan['report']['target_existing_geometry_preserved'])
            spec.variant_mode='separate';spec.destination_variant='Imported'
            options=m.Options([spec],str(root/'combined'),name='Combined',saved_sources_confirmed=True,acknowledge_outline_change=True)
            result=engine.merge(options)
            self.check_states(Path(result['project']),'Imported')

if __name__=='__main__':unittest.main()
