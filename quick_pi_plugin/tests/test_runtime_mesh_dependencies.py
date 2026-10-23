"""Managed workers provision explicitly requested nested mesh backends offline."""
import copy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch
from quick_pi_plugin import service
from wayricad_runtime.runtime_setup import REQUIREMENTS_QUICK_PI


class RuntimeMeshDependenciesTests(unittest.TestCase):
    def test_pi_probes_native_geometry_modules_without_loading_all_vtk(self):
        self.assertNotIn('vtk',REQUIREMENTS_QUICK_PI)
        for name in ('vtkmodules.vtkFiltersCore','vtkmodules.vtkFiltersGeneral','vtkmodules.vtkFiltersModeling'):
            self.assertEqual(REQUIREMENTS_QUICK_PI[name],'vtk>=9.3,<10')

    def assert_worker_requirements(self,request,gmsh):
        before=copy.deepcopy(request);runtime_before=dict(REQUIREMENTS_QUICK_PI)
        def completed(command,**kwargs):
            self.assertEqual(command[1],'-I')
            self.assertEqual(command[3],'--worker')
            self.assertEqual(json.loads(Path(command[4]).read_text(encoding='utf-8')),request)
            Path(command[5]).write_text('{"dependency_fixture": true}',encoding='utf-8')
            return types.SimpleNamespace(poll=lambda:0,returncode=0)
        with patch('wayricad_runtime.runtime_setup.ensure_runtime',return_value='fixture-python.exe') as ensure, \
             patch('wayricad_runtime.runtime_setup.child_environment',return_value={}), \
             patch.object(service.subprocess,'Popen',side_effect=completed):
            self.assertEqual(service.run_job(request),{'dependency_fixture':True})
        expected={name:spec for name,spec in REQUIREMENTS_QUICK_PI.items() if name!='kipy'}
        if gmsh:expected['gmsh']='gmsh>=4.11,<5'
        ensure.assert_called_once_with(expected)
        self.assertEqual(request,before)
        self.assertEqual(REQUIREMENTS_QUICK_PI,runtime_before)

    def test_top_level_explicit_gmsh_and_full3d(self):
        for request in ({'action':'solve','mesh_backend':'gmsh'},
                        {'action':'mesh','model_dimension':'3d'}):
            with self.subTest(request=request):self.assert_worker_requirements(request,True)

    def test_batch_supply_case_full3d_and_independent_return(self):
        for case in ({'electrical':{'mesh_backend':'gmsh'}},
                     {'electrical':{'model_dimension':'3d'}},
                     {'electrical':{'mesh_backend':'vtk'},'return_conduction':{'net':'GND','mesh_backend':'gmsh'}}):
            with self.subTest(case=case):
                self.assert_worker_requirements({'action':'batch','study':{'cases':[{},case]}},True)

    def test_marble_shaped_shared_ground_selection(self):
        request={'action':'batch','study':{'cases':[
            {'name':'3V3','electrical':{'net':'+3.3P','mesh_backend':'vtk'}},
            {'name':'USB','electrical':{'net':'+3V3_USB','mesh_backend':'auto'}}],
            'shared_returns':[{'name':'Shared ground','net':'GND','source_terminals':['J21.1','J21.3'],
                               'loads':[{'case':'3V3','sink':'chip','terminals':['U54.10']}],
                               'mesh_backend':'gmsh','max_cells':2000000}]}}
        self.assert_worker_requirements(request,True)
        request['study']['shared_returns'][0].pop('mesh_backend')
        request['study']['shared_returns'][0]['model_dimension']='3d'
        self.assert_worker_requirements(request,True)

    def test_default_auto_vtk_and_unrelated_nested_data_do_not_add_gmsh(self):
        for request in ({},{'action':'solve','mesh_backend':'auto'},
                        {'action':'solve','mesh_backend':'vtk'},
                        {'action':'batch','study':{'cases':[{'electrical':{'mesh_backend':'auto'},
                            'metadata':{'mesh_backend':'gmsh'}}],
                            'shared_returns':[{'mesh_backend':'vtk'}],
                            'unrelated':{'model_dimension':'3d'}}},
                        {'action':'inspect','study':{'cases':[{'electrical':{'mesh_backend':'gmsh'}}]}}):
            with self.subTest(request=request):self.assert_worker_requirements(request,False)

    def test_malformed_study_shapes_are_left_to_worker_validation(self):
        for study in (None,[],{'cases':None,'shared_returns':None},
                      {'cases':[None,5,{'electrical':[]}],'shared_returns':[None,5]}):
            with self.subTest(study=study):
                self.assertFalse(service._requires_gmsh({'action':'batch','study':study}))


if __name__=='__main__':unittest.main()
