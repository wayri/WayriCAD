"""Candidate filtering agrees bit-for-bit with the original Matplotlib predicate."""
import unittest
from unittest.mock import patch
import numpy as np
from matplotlib.path import Path
from quick_pi_plugin.mesh import contains


def original_contains(points,polygons):
    points=np.asarray(points,dtype=float)[:,:2]
    result=np.zeros(len(points),dtype=bool)
    for polygon in polygons:
        outer=np.asarray(polygon['outer'],dtype=float)
        area=np.sum(outer[:,0]*np.roll(outer[:,1],-1)-outer[:,1]*np.roll(outer[:,0],-1))
        inside=Path(np.vstack((outer,outer[0]))).contains_points(points,radius=1e-8 if area>0 else -1e-8)
        for ring in polygon.get('holes',[]):
            ring=np.asarray(ring,dtype=float)
            area=np.sum(ring[:,0]*np.roll(ring[:,1],-1)-ring[:,1]*np.roll(ring[:,0],-1))
            inside &= ~Path(np.vstack((ring,ring[0]))).contains_points(points,radius=-1e-8 if area>0 else 1e-8)
        result |= inside
    return result


def probes(ring):
    ring=np.asarray(ring);following=np.roll(ring,-1,axis=0)
    edges=following-ring;length=np.linalg.norm(edges,axis=1)
    normal=np.column_stack((-edges[:,1],edges[:,0]))/np.maximum(length[:,None],1e-300)
    return np.vstack([ring,following,(ring+following)/2,
        *[(ring+following)/2+normal*offset for offset in
          (-2e-8,-5.00001e-9,-5e-9,-4.99999e-9,-1e-12,0,1e-12,4.99999e-9,5e-9,5.00001e-9,2e-8)],
        *[ring+offset for offset in ((1e-8,0),(-1e-8,0),(0,1e-8),(0,-1e-8))]])


class ContainmentCandidatesTests(unittest.TestCase):
    def assert_membership(self,points,polygons):
        np.testing.assert_array_equal(contains(points,polygons),original_contains(points,polygons))

    def test_random_rotations_winding_holes_and_near_boundaries(self):
        rng=np.random.default_rng(1941)
        for iteration in range(36):
            angles=np.sort(rng.uniform(0,2*np.pi,24))
            radii=rng.uniform(.3,3,24)  # Concave jagged contours.
            outer=np.column_stack((np.cos(angles),np.sin(angles)))*radii[:,None]
            holes=[]
            for position in ((-.3,0),(.3,.2),(0,-.25)):
                angle=np.linspace(0,2*np.pi,17,endpoint=False)+rng.uniform(0,6)
                holes.append(np.column_stack((np.cos(angle),np.sin(angle)))*.12+position)
            shift=rng.uniform(-300,300,2)
            outer+=shift;holes=[h+shift for h in holes]
            if iteration%2:outer=outer[::-1]
            if iteration%3:holes=[h[::-1] for h in holes]
            points=np.vstack([rng.uniform(-4,4,(2000,2))+shift,probes(outer),
                              *[probes(h) for h in holes]])
            polygons=[{'outer':outer,'holes':holes}]
            # Overlapping regions must not erase copper filled by another region.
            if iteration%2:polygons.append({'outer':holes[0],'holes':[]})
            with self.subTest(iteration=iteration):self.assert_membership(points,polygons)

    def test_acute_reversals_duplicate_vertices_tiny_and_large_coordinates(self):
        rings=[[[0,0],[10,1e-11],[0,1e-9]],
               [[0,0],[5,0],[5,1],[2.5,1e-12],[0,1]],
               [[0,0],[1,0],[1,0],[1,1],[0,1],[0,0]],
               [[0,0],[1,0],[0,0],[0,1]],
               [[0,0],[1,0],[1,1],[0,1]]]
        rng=np.random.default_rng(901)
        for base in rings:
            for scale,shift in ((1.,0.),(1e-10,0.),(1e-6,100.),(1000.,1e8)):
                ring=np.asarray(base)*scale+shift
                points=np.vstack([probes(ring),rng.uniform(-1,12,(1000,2))*scale+shift])
                for reverse in (False,True):
                    shape=ring[::-1] if reverse else ring
                    with self.subTest(base=base,scale=scale,shift=shift,reverse=reverse):
                        self.assert_membership(points,[{'outer':shape,'holes':[]}])
                        extent=np.array([[-20,-20],[20,-20],[20,20],[-20,20]])*max(scale,1e-7)+shift
                        self.assert_membership(points,[{'outer':extent,'holes':[shape]}])

    def test_nonfinite_points_and_rings_preserve_native_fallback(self):
        points=np.array([[0,0],[.5,.5],[1,1],[np.nan,0],[0,np.inf],[-np.inf,0]])
        for ring in ([[0,0],[1,0],[1,1],[0,1]],
                     [[0,0],[1,0],[np.nan,np.nan],[1,1],[0,1]]):
            with np.errstate(invalid='ignore'):
                self.assert_membership(points,[{'outer':ring,'holes':[]}])
        self.assert_membership(np.empty((0,2)),[{'outer':[[0,0],[1,0],[0,1]],'holes':[]}])
        self.assert_membership(points,[])

    def test_dense_drill_field_reduces_predicate_points_without_changing_membership(self):
        rng=np.random.default_rng(94);points=rng.uniform(0,100,(30000,2))
        angle=np.linspace(0,2*np.pi,24,endpoint=False)
        circle=np.column_stack((np.cos(angle),np.sin(angle)))*.16
        holes=[circle+center for center in rng.uniform(1,99,(400,2))]
        points=np.vstack([points,*[probes(h) for h in holes[:8]]])
        polygons=[{'outer':[[0,0],[100,0],[100,100],[0,100]],'holes':holes}]
        native=Path.contains_points;counts=[]
        def counted(path,coordinates,*args,**kwargs):
            counts.append(len(coordinates));return native(path,coordinates,*args,**kwargs)
        with patch.object(Path,'contains_points',counted):
            expected=original_contains(points,polygons)
        old=sum(counts);counts.clear()
        with patch.object(Path,'contains_points',counted):
            actual=contains(points,polygons)
        np.testing.assert_array_equal(actual,expected)
        self.assertLess(sum(counts),old*.01)
        self.assertEqual(counts[0],len(points))

    def test_overlapping_outer_union_skips_already_covered_points(self):
        points=np.array([[.5,.5],[2,2],[10,10]])
        polygon={'outer':[[0,0],[1,0],[1,1],[0,1]],'holes':[]}
        original=Path.contains_points;counts=[]
        def counted(path,coordinates,*args,**kwargs):
            counts.append(len(coordinates));return original(path,coordinates,*args,**kwargs)
        with patch.object(Path,'contains_points',counted):
            result=contains(points,[polygon,polygon])
        np.testing.assert_array_equal(result,[True,False,False])
        self.assertEqual(counts,[2,1])


if __name__=='__main__':unittest.main()
