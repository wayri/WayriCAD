"""Local conforming refinement preserves copper domains within exact budgets."""
import importlib.util
import math
import unittest
from unittest.mock import patch
import numpy as np
from quick_pi_plugin.mesh import _refine_long_edges,triangulate_gmsh,contains
from quick_pi_plugin.solver import solve


def area(points,cells):
    a=points[cells[:,1],:2]-points[cells[:,0],:2]
    b=points[cells[:,2],:2]-points[cells[:,0],:2]
    return (a[:,0]*b[:,1]-a[:,1]*b[:,0])/2


def edges(cells):
    return np.unique(np.sort(cells[:,[[0,1],[1,2],[2,0]]].reshape(-1,2),axis=1),axis=0,return_counts=True)


def rectangle(x0,y0,x1,y1):
    return {'outer':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],'holes':[]}


class LocalRefinementTests(unittest.TestCase):
    def test_one_two_three_marked_edges_have_k_plus_one_children_and_preserve_orientation(self):
        shapes=[([[0,0,0],[2,0,0],[1,.25,0]],2),
                ([[0,0,0],[2,0,0],[0,.5,0]],3),
                ([[0,0,0],[2,0,0],[1,math.sqrt(3),0]],4)]
        for points,count in shapes:
            for winding in ((0,1,2),(0,2,1)):
                with self.subTest(children=count,winding=winding):
                    original=np.asarray(points,float);cells=np.asarray([winding])
                    p,t,info=_refine_long_edges(original,cells,1.5,count)
                    self.assertEqual(len(t),count);self.assertEqual(info['local_refinement_passes'],1)
                    self.assertTrue(np.array_equal(p[:3],original))
                    self.assertTrue(np.array_equal(cells,np.asarray([winding])))
                    self.assertTrue(np.all(area(p,t)*area(original,cells)[0]>0))
                    self.assertAlmostEqual(area(p,t).sum(),area(original,cells).sum(),14)
                    self.assertLessEqual(info['maximum_edge_mm'],1.5*(1+1e-8))

    def test_shared_edge_has_one_midpoint_and_no_hanging_interface(self):
        original=np.array([[0,0,0],[2,0,0],[2,1,0],[0,1,0]],float)
        cells=np.array([[0,1,2],[0,2,3]])
        p,t,info=_refine_long_edges(original,cells,1.8,6)
        self.assertEqual(len(t),6)
        middle=np.flatnonzero(np.all(p==[1,.5,0],axis=1))
        self.assertEqual(len(middle),1)
        all_edges,counts=edges(t)
        self.assertTrue(np.all(counts<=2))
        for edge in ((0,int(middle[0])),(int(middle[0]),2)):
            self.assertEqual(counts[np.all(all_edges==sorted(edge),axis=1)].tolist(),[2])
        self.assertAlmostEqual(area(p,t).sum(),2.,14)

    def test_locality_avoids_global_quadrupling_and_budget_precedes_child_allocation(self):
        points=[[0,0,0],[2,0,0],[1,.25,0]];cells=[[0,1,2]]
        for index in range(20):
            start=len(points);x=10+index
            points.extend([[x,0,0],[x+.1,0,0],[x,.1,0]]);cells.append([start,start+1,start+2])
        points=np.asarray(points);cells=np.asarray(cells)
        p,t,info=_refine_long_edges(points,cells,1.5,22)
        self.assertEqual(len(t),22);self.assertEqual(info['initial_triangles'],21)
        for unchanged in cells[1:]:self.assertTrue(np.any(np.all(t==unchanged,axis=1)))
        with patch('quick_pi_plugin.mesh.np.vstack',side_effect=AssertionError('child vertices allocated before budget check')):
            with self.assertRaisesRegex(ValueError,'needs 22.*budget'):
                _refine_long_edges(points,cells,1.5,21)

    def test_multilevel_refinement_is_deterministic_conforming_and_cancellable(self):
        original=np.array([[0,0,0],[8,0,0],[8,1,0],[0,1,0]],float)
        cells=np.array([[0,1,2],[0,2,3]])
        a,ta,info=_refine_long_edges(original,cells,.4,10000)
        b,tb,_=_refine_long_edges(original,cells,.4,10000)
        self.assertTrue(np.array_equal(a,b));self.assertTrue(np.array_equal(ta,tb))
        self.assertGreater(info['local_refinement_passes'],1)
        self.assertLessEqual(info['maximum_edge_mm'],.4*(1+1e-8))
        self.assertAlmostEqual(area(a,ta).sum(),8.,12)
        e,counts=edges(ta);self.assertTrue(np.all(counts<=2))
        for edge in e[counts==1]:
            xy=a[edge,:2]
            self.assertTrue(np.all(xy[:,0]==0) or np.all(xy[:,0]==8) or np.all(xy[:,1]==0) or np.all(xy[:,1]==1))
        calls=[]
        def cancel():
            calls.append(1);return len(calls)==2
        with self.assertRaises(InterruptedError):_refine_long_edges(original,cells,.4,10000,cancel)
        with self.assertRaisesRegex(ValueError,'requested edge'):
            _refine_long_edges(original,cells,.01,10000,max_passes=0)


@unittest.skipIf(importlib.util.find_spec('gmsh') is None,'Gmsh required')
class NativeGmshRefinementTests(unittest.TestCase):
    def test_local_budget_accepts_strip_without_global_refine_or_vtk_and_matches_analytic_resistance(self):
        import gmsh
        import builtins
        original_import=builtins.__import__
        def no_vtk(name,*args,**kwargs):
            if name=='vtk' or name.startswith('vtkmodules'):raise AssertionError('Gmsh refinement must not use VTK')
            return original_import(name,*args,**kwargs)
        with patch.object(gmsh.model.mesh,'refine',side_effect=AssertionError('Global refinement is forbidden')),patch('builtins.__import__',side_effect=no_vtk):
            p,t,info=triangulate_gmsh([rectangle(0,0,3,1)],.7,max_cells=50)
        self.assertGreater(info['local_refinement_passes'],0)
        self.assertLessEqual(len(t),50);self.assertGreater(info['initial_triangles']*4,50)
        mesh={'points_mm':p,'triangles':t,'triangle_thickness_mm':np.full(len(t),.035)}
        result=solve(mesh,np.flatnonzero(abs(p[:,0])<1e-9),np.flatnonzero(abs(p[:,0]-3)<1e-9),sink_current=2)
        expected=1.724e-8*.003/(.001*.000035)
        self.assertAlmostEqual(result['drop_over_current_ohm'],expected,11)
        self.assertAlmostEqual(result['total_power_W'],4*expected,11)
        self.assertLess(result['current_balance_error_A'],1e-9)
        self.assertLess(result['energy_relative_error'],1e-9)

    def test_shared_contact_edges_and_drilled_void_survive_native_local_refinement(self):
        polygons=[rectangle(0,0,1,2),rectangle(1,0,4,2)]
        polygons[1]['holes']=[[[2,.5],[3,.5],[3,1.5],[2,1.5]]]
        p,t,info=triangulate_gmsh(polygons,.55)
        self.assertAlmostEqual(info['area_mm2'],7.,10)
        self.assertLessEqual(info['maximum_edge_mm'],.55*(1+1e-8))
        self.assertTrue(contains(p[t].mean(axis=1),polygons).all())
        e,counts=edges(t)
        shared=np.all(abs(p[e,0]-1)<1e-9,axis=1)
        self.assertTrue(shared.any());self.assertTrue(np.all(counts[shared]==2))
        # Every exterior edge remains on an original rectangle/hole boundary.
        for edge in e[counts==1]:
            xy=p[edge,:2]
            self.assertTrue(any(np.all(abs(xy[:,axis]-value)<1e-9) for axis,value in
                                ((0,0),(0,4),(1,0),(1,2),(0,2),(0,3),(1,.5),(1,1.5))))


if __name__=='__main__':unittest.main()
