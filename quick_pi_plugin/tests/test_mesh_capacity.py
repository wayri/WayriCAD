"""Explicit resource budgets must reach meshing/solving without changing physics."""
import contextlib
import builtins
import io
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from quick_pi_plugin import service,cli
from quick_pi_plugin.solver import solve,SolverError
from quick_pi_plugin.tests.test_solver import strip
from quick_pi_plugin.tests import test_shared_return as shared_fixture
from quick_pi_plugin.tests import test_service_multisink as native_fixture


class MeshCapacityTests(unittest.TestCase):
    def test_request_range_and_invalid_values_before_board_io(self):
        self.assertEqual(service.mesh_cell_budget({}),400000)
        for value in (1000,400000,1500000,2000000):
            self.assertEqual(service.mesh_cell_budget({'max_cells':value}),value)
        for value in (True,False,None,0,-1,999,2000001,1000.,'1000',float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'max_cells'):
                service.execute({'action':'solve','max_cells':value})
        for extra in ({'model_dimension':'3d'},{'series':[{}]},{'package_conduction':[{}]}):
            with self.subTest(extra=extra),self.assertRaisesRegex(ValueError,'separate budgets'):
                service.execute({'max_cells':1500000,**extra})

    def test_saved_request_propagates_budget_and_default_solver_guards(self):
        mesh,source,sink=strip()
        specs=[{'id':'load','nodes':sink,'current_A':1.}]
        native_import=builtins.__import__
        def fixture_import(name,*args,**kwargs):
            return types.SimpleNamespace(LoadBoard=lambda _:object()) if name=='pcbnew' else native_import(name,*args,**kwargs)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'fixture.kicad_pcb';path.write_text('(kicad_pcb)')
            base={'action':'solve','board_path':str(path),'net':'VCC',
                  'source_terminal':'J1.1','sink_terminal':'J2.1'}
            for explicit in (None,1000,1500000,2000000):
                request=dict(base)
                if explicit is not None:request['max_cells']=explicit
                with self.subTest(explicit=explicit), \
                     patch('builtins.__import__',side_effect=fixture_import), \
                     patch('quick_pi_plugin.board_geometry.extract',return_value={}), \
                     patch('quick_pi_plugin.mesh.build_mesh',return_value=mesh) as mesher, \
                     patch('quick_pi_plugin.terminals.resolve_units',return_value=([{'id':'s'}],source,specs,{})), \
                     patch('quick_pi_plugin.solver.solve',wraps=solve) as solver:
                    result=service.execute(request)['result']
                    self.assertEqual(mesher.call_args.kwargs['max_cells'],400000 if explicit is None else explicit)
                    if explicit is None:
                        self.assertNotIn('mesh_cell_budget',solver.call_args.kwargs)
                        self.assertNotIn('mesh_vertex_budget',solver.call_args.kwargs)
                    else:
                        self.assertEqual(solver.call_args.kwargs['mesh_cell_budget'],max(500000,explicit))
                        self.assertEqual(solver.call_args.kwargs['mesh_vertex_budget'],max(250000,min(2000000,explicit)))
                    self.assertAlmostEqual(result['drop_over_current_ohm'],1.724e-8*.01/(.001*.000035),12)
                    self.assertLess(result['energy_relative_error'],1e-10)

    def test_shared_group_and_case_propagation_and_validation(self):
        fixture=shared_fixture.SharedReturnTests();fixture.setUp()
        try:
            value=shared_fixture.study()
            value['shared_returns'][0]['max_cells']=1500000
            value['cases'][0]['electrical']['max_cells']=1000000
            result=fixture.run_study(value)
            self.assertEqual(result['status'],'COMPLETED')
            self.assertEqual([r.get('max_cells') for r in fixture.calls],[1000000,None,1500000])
            for bad in (True,0,2000001,1500000.,'1500000'):
                value['shared_returns'][0]['max_cells']=bad
                with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'max_cells'):
                    shared_fixture.validate_study(value)
        finally:fixture.doCleanups()

    def test_solver_invalid_budget_fails_before_input_access(self):
        class NoAccess:
            def __getitem__(self,key):raise AssertionError('Read mesh before validating budget')
        for name,minimum,maximum in (('mesh_cell_budget',1,2000000),('mesh_vertex_budget',2,2000000)):
            for bad in (True,None,0,-1,minimum-1,maximum+1,1000.,'1000',float('nan'),float('inf')):
                with self.subTest(name=name,bad=bad),self.assertRaisesRegex(SolverError,name):
                    solve(NoAccess(),[],**{name:bad})

    def test_solver_capacity_rejected_before_array_allocation(self):
        class LengthOnly:
            def __init__(self,count):self.count=count
            def __len__(self):return self.count
            def __array__(self,*args,**kwargs):raise AssertionError('Allocated oversized input')
        for key,default in (('points_mm',250000),('triangles',500000)):
            with self.subTest(key=key),self.assertRaisesRegex(SolverError,'mesh budget'):
                solve({key:LengthOnly(default+1)},[],[])
        mesh,source,sink=strip()
        for kwargs in ({'mesh_cell_budget':len(mesh['triangles'])-1},
                       {'mesh_vertex_budget':len(mesh['points_mm'])-1}):
            with self.assertRaisesRegex(SolverError,'mesh budget'):solve(mesh,source,sink,**kwargs)
        result=solve(mesh,source,sink,mesh_cell_budget=len(mesh['triangles']),
                     mesh_vertex_budget=len(mesh['points_mm']))
        self.assertLess(result['current_balance_error_A'],1e-10)
        enlarged=solve(mesh,source,sink,mesh_cell_budget=2000000,mesh_vertex_budget=2000000)
        self.assertAlmostEqual(enlarged['drop_over_current_ohm'],result['drop_over_current_ohm'],14)
        self.assertLess(enlarged['energy_relative_error'],1e-10)
        with self.assertRaisesRegex(SolverError,'mesh budget'):
            solve({'points_mm':LengthOnly(2000001)},[],[],mesh_vertex_budget=2000000)

    def test_cli_explicit_budget_and_no_implicit_override(self):
        args=['fixture.kicad_pcb','--net','VCC','--source','J1.1','--sink','J2.1']
        for extra,expected in (([],None),(['--max-cells','1500000'],1500000)):
            with patch('quick_pi_plugin.service.run_job',return_value={}) as job,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(args+extra),0)
                self.assertEqual(job.call_args.args[0].get('max_cells'),expected)
        with patch('quick_pi_plugin.service.run_job') as job,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(args+['--max-cells','2000001']),2)
            job.assert_not_called()
        with patch('quick_pi_plugin.service.run_job') as job,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(args+['--max-cells','1500000','--model-dimension','3d']),2)
            job.assert_not_called()

    @unittest.skipUnless(native_fixture.NATIVE,'Requires native KiCad and the Quick PI scientific runtime')
    def test_native_saved_board_explicit_capacity_preserves_current_and_power(self):
        fixture=native_fixture.SavedBoardMultisinkTests();fixture.setUp()
        try:
            bundle=service.execute({**fixture.request,'max_cells':1500000})
            self.assertEqual(bundle['request']['max_cells'],1500000)
            self.assertAlmostEqual(bundle['result']['source_current_A'],3,8)
            self.assertLess(bundle['result']['energy_relative_error'],1e-6)
            self.assertEqual(bundle['geometry']['source_sha256'],fixture.before)
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
