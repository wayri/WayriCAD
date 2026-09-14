"""Native VTK copper meshing acceptance, including physical FEM integration."""
import unittest
import numpy as np
from quick_pi_plugin.mesh import triangulate, contains, build_mesh
from quick_pi_plugin.solver import solve


def rectangle(x0,y0,x1,y1):
    return {'outer':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],'holes':[]}


class MeshTests(unittest.TestCase):
    def test_hole_area_and_boundary_containment(self):
        polygon=rectangle(0,0,4,4);polygon['holes']=[[[1,1],[1,3],[3,3],[3,1]]]
        p,t,r=triangulate([polygon],.4)
        self.assertAlmostEqual(r['area_mm2'],12,9)
        self.assertLessEqual(r['maximum_edge_mm'],.40000001)
        self.assertTrue(contains(p[t].mean(axis=1),[polygon]).all())
        self.assertEqual(contains([[2,2],[1,2],[.5,.5]],[polygon]).tolist(),[False,True,True])

    def test_disconnected_islands_preserved(self):
        polygons=[rectangle(0,0,1,1),rectangle(2,0,3,1)]
        p,t,r=triangulate(polygons,.5)
        self.assertAlmostEqual(r['area_mm2'],2,9)
        self.assertTrue(all(np.ptp(p[tri,0])<1.1 for tri in t))
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        edges=np.concatenate((t[:,[0,1]],t[:,[1,2]],t[:,[2,0]]))
        graph=coo_matrix((np.ones(len(edges)),(edges[:,0],edges[:,1])),shape=(len(p),len(p)))
        self.assertEqual(connected_components(graph,directed=False)[0],2)

    def test_point_only_copper_contact_is_not_a_conducting_short(self):
        from quick_pi_plugin.solver import SolverError
        p,t,r=triangulate([rectangle(0,0,1,1),rectangle(1,1,2,2)],.5)
        self.assertGreater(r['point_contacts_separated'],0)
        mesh={'points_mm':p,'triangles':t,'triangle_thickness_mm':np.full(len(t),.035)}
        with self.assertRaisesRegex(SolverError,'disconnected'):
            solve(mesh,np.flatnonzero(p[:,0]==0),np.flatnonzero(p[:,0]==2))

    def test_many_aligned_holes_preserve_area_and_edges(self):
        import math
        polygon=rectangle(0,0,12,8)
        polygon['holes']=[[[x+.2*math.cos(a),y+.2*math.sin(a)]
                           for a in np.linspace(0,2*math.pi,24,endpoint=False)]
                          for x in (1,2,3,4,7,8,9,10) for y in (1,2,3,5,6,7)]
        p,t,r=triangulate([polygon],.5)
        hole_area=24*.2*.2*math.sin(2*math.pi/24)/2
        self.assertAlmostEqual(r['area_mm2'],96-48*hole_area,8)

    def test_contact_boundary_t_junctions_are_split_conformingly(self):
        left=rectangle(0,0,1,1);left['outer'].insert(2,[1,.5])
        p,t,_=triangulate([left,rectangle(1,0,2,1)],.4)
        edges=np.sort(np.concatenate((t[:,[0,1]],t[:,[1,2]],t[:,[2,0]])),axis=1)
        edges,count=np.unique(edges,axis=0,return_counts=True)
        unpaired=[edge for edge in edges[count==1] if np.allclose(p[edge,0],1)]
        self.assertEqual(unpaired,[])
        mesh={'points_mm':p,'triangles':t,'triangle_thickness_mm':np.full(len(t),.035)}
        r=solve(mesh,np.flatnonzero(p[:,0]==0),np.flatnonzero(p[:,0]==2))
        self.assertAlmostEqual(r['drop_over_current_ohm'],1.724e-8*.002/(.001*.000035),12)

    def test_budget_and_cancel_are_bounded(self):
        with self.assertRaisesRegex(ValueError,'budget|exceeds'):
            triangulate([rectangle(0,0,10,10)],.01,max_cells=20)
        with self.assertRaises(InterruptedError):
            triangulate([rectangle(0,0,10,10)],1,cancelled=lambda:True)

    def test_barrel_contacts_and_terminal_boundaries_survive_meshing(self):
        # Two layers, separate source/sink strips. The interior contact region
        # explicitly partitions copper, so a coarse mesh still finds the via.
        copper=rectangle(0,0,3,1)
        regions=[rectangle(0,0,1,1),rectangle(1,0,2,1),rectangle(2,0,3,1)]
        contact=rectangle(1,0,2,1)
        geometry={'layers':[{'id':i,'name':str(i),'z_mm':z,'thickness_mm':.035,
                             'polygons':[copper],'mesh_regions':regions} for i,z in ((0,0),(2,1.6))],
                  'terminals':[{'id':'source','polygons':{'0':[rectangle(0,0,.01,1)]}},
                               {'id':'sink','polygons':{'2':[rectangle(2.99,0,3,1)]}}],
                  'vias':[{'id':'via','layers':[0,2],'x_mm':1.5,'y_mm':.5,
                           'diameter_mm':.6,'drill_mm':.3,'polygons':{'0':[contact],'2':[contact]}}]}
        mesh=build_mesh(geometry,edge_mm=.8)
        self.assertEqual(len(mesh['vias']),1)
        self.assertAlmostEqual(mesh['vias'][0]['length_mm'],1.6)
        self.assertTrue(mesh['terminal_nodes']['source']);self.assertTrue(mesh['terminal_nodes']['sink'])
        r=solve(mesh,mesh['terminal_nodes']['source'],mesh['terminal_nodes']['sink'])
        self.assertAlmostEqual(r['vias'][0]['current_A'],1,9)
        self.assertLess(r['energy_relative_error'],1e-10)


if __name__=='__main__':unittest.main()
