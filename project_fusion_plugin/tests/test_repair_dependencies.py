import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from dataclasses import asdict

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('fusion_test')
package.__path__=[str(ROOT)]
sys.modules.setdefault('fusion_test',package)
from fusion_test import repair,dependencies,sexpr as sx
from fusion_test.model import SourceSpec,MergeError,validate_source_aliases
from fusion_test.netlist import Netlist

UUID='11111111-1111-4111-8111-111111111111'
OLD='22222222-2222-4222-8222-222222222222'

class RepairTests(unittest.TestCase):
    def test_root_path_is_unique_or_refused(self):
        def symbol(path):return ['symbol',['instances',['project','Example',['path',path,['reference','R1']]]]]
        tree=['kicad_sch',['uuid',UUID],symbol('/'+OLD)]
        report=repair.normalize_root_paths(tree,'Example')
        self.assertEqual(report[0]['instances'],1)
        self.assertEqual(repair.normalize_root_paths(tree,'Example'),[])
        ambiguous=['kicad_sch',['uuid',UUID],symbol('/'+OLD),symbol('/'+UUID)]
        with self.assertRaises(MergeError):repair.normalize_root_paths(ambiguous,'Example')

    def test_pad_geometry_rotation_rounding_and_resize(self):
        f=['footprint','Example',['at','1','2','90'],['pad','1','smd','rect',['at','0.54001','0','90'],['size','0.6','0.6'],['uuid',UUID],['net','old']]]
        g=copy.deepcopy(f);g[2]=['at','3','4','180'];g[3][4]=['at','0.54','0','180']
        self.assertEqual(repair.pad_geometry_signature(f),repair.pad_geometry_signature(g))
        g[3][5]=['size','0.8','0.6']
        self.assertNotEqual(repair.pad_geometry_signature(f),repair.pad_geometry_signature(g))

    def test_partition_change_and_added_parts(self):
        def fp(ref,pins):return ['footprint','lib:R',['property','Reference',ref],*[['pad',p,'smd','rect',['net',sx.q(n)]] for p,n in pins]]
        board=['kicad_pcb',fp('R1',[('1','old'),('2','gate')]),fp('Q1',[('1','gate'),('','old')])]
        net=Netlist(nets={'renamed':{('R1','1'),('R2','1')},'splitA':{('R1','2')},'splitB':{('Q1','1')}})
        mapping,changed=repair.net_partition_map(board,net)
        self.assertEqual(mapping,{'old':'renamed'});self.assertEqual(changed,['gate'])

    def fixture(self,root):
        source=root/'source';source.mkdir()
        for ext in ('.kicad_pro','.kicad_sch','.kicad_pcb'):(source/('Example'+ext)).write_text('original')
        (source/'local').mkdir();(source/'local'/'model.step').write_text('geometry')
        return source,SourceSpec(str(source/'Example.kicad_pro'),'Example',variant='EM')

    def test_preview_and_apply_only_copies_and_stale(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source,spec=self.fixture(root);original=repair.fingerprint(source)
            def compile_copy(candidate,*args):
                path=Path(candidate.project);path.write_text('compiled')
                data=asdict(candidate);data['variant']='<Default>'
                return SourceSpec(**data),{'actions':[],'manufacturing_ready':False}
            with patch.object(repair,'_native_compile',side_effect=compile_copy):
                plan=repair.preview_repair(spec)
                self.assertEqual(repair.fingerprint(source),original)
                result,report=repair.apply_repair(plan,root/'candidate')
                self.assertEqual(result.variant,'<Default>');self.assertEqual(Path(result.project).read_text(),'compiled')
                self.assertEqual(repair.fingerprint(source),original)
                self.assertEqual((root/'candidate'/'local'/'model.step').read_text(),'geometry')
                with self.assertRaises(MergeError):repair.apply_repair(plan,root/'candidate')
                (source/'Example.kicad_sch').write_text('changed')
                with self.assertRaises(MergeError):repair.apply_repair(plan,root/'stale')
                self.assertFalse((root/'stale').exists())

    def test_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source,spec=self.fixture(root)
            plan=repair.RepairPlan(spec,repair.fingerprint(source),False,{})
            with patch.object(repair,'_native_compile',side_effect=MergeError('native failed')):
                with self.assertRaises(MergeError):repair.apply_repair(plan,root/'candidate')
            self.assertFalse((root/'candidate').exists());self.assertFalse(list(root.glob('.fusion-repair-*')))

    def test_unsafe_aliases_refused(self):
        with self.assertRaises(MergeError):validate_source_aliases([SourceSpec('Example.kicad_pro','../escape')])
        with self.assertRaises(MergeError):validate_source_aliases([SourceSpec('Example.kicad_pro','A'),SourceSpec('Other.kicad_pro','a')])

    def test_dependencies_suggest_unique_only(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'models').mkdir();(root/'models'/'part.step').write_text('model')
            (root/'library').mkdir();(root/'library'/'R.kicad_mod').write_text('footprint')
            source=types.SimpleNamespace(project_file=root/'Example.kicad_pro',alias='Example',board=['kicad_pcb',['footprint','Old:R']],sheets=[],libraries={})
            items=[{'reference':'part.step','kind':'3D model'},{'reference':'Old','kind':'footprint library'}]
            suggestions=dependencies.suggest_paths(source,items)
            self.assertEqual(len(suggestions),2)
            (root/'part.step').write_text('another')
            self.assertEqual(len(dependencies.suggest_paths(source,items)),1)

    def test_dependency_copies_and_stale_refusal(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source,spec=self.fixture(root)
            plan={'specs':[asdict(spec)],'hashes':{'Example':repair.fingerprint(source)},'report':{'suggestions':[{'source':'Example','action':'path_remap','reference':'model.step','path':str(source/'local/model.step')}]}}
            result=dependencies.apply_dependencies(plan,root/'candidate')
            self.assertEqual(Path(result[0].path_remaps['model.step']).resolve(),(root/'candidate/Example/local/model.step').resolve())
            (source/'local/model.step').write_text('changed')
            with self.assertRaises(MergeError):dependencies.apply_dependencies(plan,root/'stale')

if __name__=='__main__':unittest.main()
