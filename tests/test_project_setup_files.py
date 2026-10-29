"""Chosen input/result files retain exact data and reject incompatible custody."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from wayricad_runtime.project_setup import make_setup,save_setup,load_setup,SourceChangedError
from wayricad_runtime.project_results import save_result,load_result


class SetupFiles(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.board=self.root/'example.kicad_pcb';self.board.write_text('(kicad_pcb)')

    def test_all_plugins_roundtrip_chosen_names_without_mutation(self):
        for plugin in ('quick-pi','quick-si','quick-therm','quick-emerge'):
            state={'current':'2.5','choices':['a','b'],'unknown':None}
            path=self.root/(plugin+'.setup.json');record=make_setup(plugin,self.board,state)
            save_setup(path,record,protected_sources=[self.board])
            self.assertEqual(load_setup(path,plugin,self.board)['state'],state)
            results={'samples':[1,None,2.75],'nested':{'frames':[[2,3]]}}
            destination=self.root/(plugin+'.result.json')
            save_result(self.root,plugin,results,destination=destination,protected_sources=[self.board])
            self.assertEqual(load_result(self.root,destination,plugin=plugin,chosen=True)['bundle'],results)
        self.assertEqual(self.board.read_text(),'(kicad_pcb)')

    def test_changed_source_review_and_wrong_plugin(self):
        path=self.root/'setup.json';save_setup(path,make_setup('quick-pi',self.board,{'net':'VCC'}))
        self.board.write_text('(kicad_pcb (changed))')
        with self.assertRaises(SourceChangedError):load_setup(path,'quick-pi',self.board)
        self.assertTrue(load_setup(path,'quick-pi',self.board,allow_changed_source=True)['source_changed'])
        with self.assertRaises(ValueError):load_setup(path,'quick-si',self.board,allow_changed_source=True)

    def test_selected_result_elsewhere_and_corruption(self):
        directory=self.root/'elsewhere';directory.mkdir();target=directory/'measurement.json'
        save_result(self.root,'pi',{'numbers':[3,4]},destination=target)
        self.assertEqual(load_result(self.root,target,plugin='pi',chosen=True)['bundle']['numbers'],[3,4])
        with self.assertRaises(ValueError):load_result(self.root,target,plugin='si',chosen=True)
        record=json.loads(target.read_bytes());record['numbers'][0]=8;target.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'hash'):load_result(self.root,target,plugin='pi',chosen=True)

    def test_setup_validation_before_mutation_and_strict_json(self):
        path=self.root/'setup.json';save_setup(path,make_setup('quick-si',self.board,{'pad':'gone'}))
        def reject(state):raise ValueError('Pad no longer exists')
        with self.assertRaisesRegex(ValueError,'Pad'):load_setup(path,'quick-si',self.board,validate_state=reject)
        with self.assertRaises(ValueError):make_setup('quick-pi',self.board,{'invalid':float('nan')})
        with self.assertRaises(ValueError):save_setup(self.board,{},protected_sources=[self.board])

    def test_uncertified_results_never_replace_declared_study_or_model_inputs(self):
        for key in ('study_input_path','model_path','ibis_file'):
            source=self.root/(key+'.json');source.write_text('{"original":true}')
            with self.assertRaisesRegex(ValueError,'overwrite'):
                save_result(self.root,'pi',{'request':{key:str(source)}},destination=source)
            self.assertEqual(source.read_text(),'{"original":true}')


if __name__=='__main__':unittest.main()
