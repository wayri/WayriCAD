"""Geometry-driven sizing retains manual control, conformity and conservation."""
import copy
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

from quick_pi_plugin.mesh import build_mesh, _refine_long_edges
from quick_pi_plugin.mesh_sizing import recommend, edge_targets, mode, sizing_html
from quick_pi_plugin.solver import solve


def geometry(width=.15):
    polygon={'outer':[[0,0],[10,0],[10,2],[0,2]],'holes':[]}
    return {'layers':[{'id':0,'name':'F.Cu','z_mm':0.,'thickness_mm':.035,'polygons':[polygon]}],
            'terminals':[],'vias':[], 'area_mm2':20.,
            'mesh_features':[{'kind':'track','id':'T1','layer':'0','width_mm':width,
                              'start_mm':[0,0],'end_mm':[10,0]}]}


class AutoMeshTests(unittest.TestCase):
    def test_host_validation_imports_do_not_require_scientific_packages(self):
        script='''import builtins,sys
sys.path.insert(0,sys.argv[1])
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.split('.')[0] in ('numpy','scipy','matplotlib','gmsh','vtk'):
        raise AssertionError('Host imported scientific dependency: '+name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from quick_pi_plugin.mesh_sizing import mode
from quick_pi_plugin import cli,service
assert mode({'mesh_sizing':'auto'})=='auto'
try: service.run_job({'mesh_sizing':'invalid'})
except ValueError: pass
else: raise AssertionError('Invalid mode accepted')
'''
        completed=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[2])],
                                 capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=30)
        self.assertEqual(completed.returncode,0,completed.stderr)

    def test_physical_width_changes_local_size_not_contour_tessellation(self):
        narrow=recommend(geometry(.09));wide=recommend(geometry(.3))
        self.assertAlmostEqual(narrow['minimum_local_target_mm'],.03)
        self.assertGreater(wide['minimum_local_target_mm'],narrow['minimum_local_target_mm'])
        dense=geometry(.09);dense['layers'][0]['polygons'][0]['outer'].insert(1,[.000001,0])
        self.assertEqual(recommend(dense)['minimum_local_target_mm'],narrow['minimum_local_target_mm'])
        self.assertIn('not mesh convergence',' '.join(narrow['limitations']))

    def test_html_summary_omits_nested_feature_arrays_but_preserves_evidence(self):
        data={'mesh_sizing':{'mode':'auto','domains':[{'net':'VCC','feature_count':1,
               'features':[{'id':'raw-sentinel'}]}]},'mesh_report':[{'maximum_target_ratio':1.}]}
        html=sizing_html(data)
        self.assertNotIn('raw-sentinel',html)
        self.assertIn('maximum_target_ratio',html)
        self.assertEqual(data['mesh_sizing']['domains'][0]['features'][0]['id'],'raw-sentinel')

    def test_local_feature_refinement_keeps_far_edges_coarse(self):
        plan=recommend(geometry())
        targets=edge_targets(np.array([[5,.03,0],[5,1.9,0]]),plan['features'],plan['background_edge_mm'])
        self.assertAlmostEqual(targets[0],.05)
        self.assertGreater(targets[1],targets[0])
        with self.assertRaises(InterruptedError):
            edge_targets([[5,.1,0]],plan['features'],.5,lambda:True)

    @unittest.skipUnless(importlib.util.find_spec('vtk'), 'Native VTK mesher is unavailable')
    def test_auto_mesh_preserves_analytic_strip_solution_and_area(self):
        geo=geometry();mesh=build_mesh(geo,sizing='auto',backend='vtk',max_cells=40000)
        points=np.array(mesh['points_mm']);cells=np.array(mesh['triangles'])
        result=solve(mesh,np.flatnonzero(np.isclose(points[:,0],0)),
                     np.flatnonzero(np.isclose(points[:,0],10)),sink_current=2.)
        self.assertAlmostEqual(result['drop_over_current_ohm'],1.724e-8*.01/(.002*.000035),places=10)
        self.assertLess(result['energy_relative_error'],1e-9)
        self.assertLess(result['current_balance_error_A'],1e-8)
        a=points[cells[:,1],:2]-points[cells[:,0],:2];b=points[cells[:,2],:2]-points[cells[:,0],:2]
        self.assertAlmostEqual(float(np.sum(abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]))/2),20.,places=9)
        self.assertLessEqual(mesh['mesh_report'][0]['maximum_target_ratio'],1+1e-8)
        self.assertEqual(mesh['mesh_sizing']['actual_triangles'],len(cells))

    @unittest.skipUnless(importlib.util.find_spec('vtk'), 'Native VTK mesher is unavailable')
    def test_manual_override_does_not_apply_geometry_field_and_budget_never_coarsens(self):
        geo=geometry(.03)
        mesh=build_mesh(geo,edge_mm=1.,sizing='manual',backend='vtk')
        self.assertEqual(mesh['edge_mm'],1.)
        self.assertEqual(mesh['mesh_sizing']['mode'],'manual')
        with self.assertRaisesRegex(ValueError,'budget|exceeds'):
            build_mesh(geo,sizing='auto',backend='vtk',max_cells=1000)
        with self.assertRaises(InterruptedError):
            build_mesh(geo,sizing='auto',backend='vtk',cancelled=lambda:True)

    def test_unknown_or_unsupported_sizing_modes_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'auto or manual'):mode({'mesh_sizing':'adaptive_magic'})
        with self.assertRaisesRegex(ValueError,'2.5D only'):mode({'mesh_sizing':'auto','model_dimension':'3d'})

    def test_adaptive_shared_edges_never_hang(self):
        points=np.array([[0,0,0],[2,0,0],[2,2,0],[0,2,0]],float)
        p,t,report=_refine_long_edges(points,[[0,1,2],[0,2,3]],3.,1000,
            target_function=lambda xy:np.where(xy[:,0]<1.1,.4,3.))
        for tri in t:
            for a,b in zip(tri,np.roll(tri,-1)):
                delta=p[b]-p[a];fraction=((p-p[a])@delta)/(delta@delta)
                hanging=(fraction>1e-8)&(fraction<1-1e-8)&(np.linalg.norm(p-(p[a]+fraction[:,None]*delta),axis=1)<1e-10)
                self.assertFalse(np.any(hanging))
        self.assertLessEqual(report['maximum_target_ratio'],1+1e-8)

    def test_cli_modes_reach_worker_and_ambiguous_modes_reject(self):
        from quick_pi_plugin.cli import main
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.kicad_pcb';path.write_text('(kicad_pcb)')
            args=[str(path),'--net','VCC','--source','J1.1','--sink','U1.1']
            with patch('quick_pi_plugin.service.run_job',return_value={'ok':True}) as worker:
                self.assertEqual(main(args+['--auto-mesh']),0)
                self.assertEqual(worker.call_args.args[0]['mesh_sizing'],'auto')
                self.assertEqual(main(args+['--mesh-edge','.2']),0)
                self.assertEqual(worker.call_args.args[0]['edge_mm'],.2)
                worker.reset_mock()
                self.assertEqual(main(args+['--auto-mesh','--mesh-edge','.2']),2)
                worker.assert_not_called()

    def test_convergence_freezes_auto_start_then_really_halves(self):
        from quick_pi_plugin.convergence import run_study
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.kicad_pcb';path.write_bytes(b'fixture')
            sha=hashlib.sha256(path.read_bytes()).hexdigest();calls=[]
            def execute(req):
                calls.append(copy.deepcopy(req))
                if req['action']=='geometry':return {'mesh_sizing_recommendation':{'background_edge_mm':.4}}
                edge=req['edge_mm'];n=round(1/edge**2)
                return {'request':req,'geometry':{'source_sha256':sha,'geometry_sha256':'same'},
                        'mesh':{'points_mm':[None]*n,'triangles':[None]*(n*2)},
                        'result':dict(voltage_drop_V=1.,drop_over_current_ohm=1.,total_power_W=1.,planar_power_W=1.,sink_current_A=1.,current_balance_error_A=0.,max_nodal_residual_A=0.,energy_relative_error=0.,max_current_density_A_mm2=1.)}
            result=run_study({'board_path':str(path),'mesh_sizing':'auto','convergence_levels':3},execute)
            self.assertEqual([req['edge_mm'] for req in calls[1:]],[.4,.2,.1])
            self.assertTrue(all(req['mesh_sizing']=='manual' for req in calls[1:]))
            self.assertIn('fixed once',result['convergence']['automatic_start_notice'])
