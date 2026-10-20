"""Independent native area/contact checks for batched plane partitioning."""
import unittest
try:import pcbnew as p
except ImportError:p=None


@unittest.skipIf(p is None,'Native KiCad polygon engine required')
class ContactPartitionTests(unittest.TestCase):
    def rectangle(self,x,y,w,h):
        poly=p.SHAPE_POLY_SET();poly.NewOutline()
        for a,b in ((x,y),(x+w,y),(x+w,y+h),(x,y+h)):poly.Append(p.FromMM(a),p.FromMM(b))
        return poly

    def native(self,record):
        poly=p.SHAPE_POLY_SET();poly.NewOutline()
        for x,y in record['outer']:poly.Append(p.FromMM(x),p.FromMM(y))
        for ring in record['holes']:
            hole=poly.NewHole()
            for x,y in ring:poly.Append(p.FromMM(x),p.FromMM(y),0,hole)
        return poly

    def test_area_voids_overlap_and_every_electrode_boundary(self):
        from quick_pi_plugin.board_geometry import _partition
        copper=self.rectangle(0,0,20,15)
        hole=self.rectangle(8,5,3,2);copper.BooleanSubtract(hole)
        # Overlapping, nested, touching and disconnected electrode regions.
        contacts=[self.rectangle(*box) for box in ((1,1,4,3),(3,2,4,4),(4,3,1,1),
                    (7,2,2,2),(12,3,2,2),(14,3,2,2),(7,4,5,4),(18,12,1,1))]
        for contact in contacts:contact.BooleanIntersection(copper)
        cells=[self.native(r) for r in _partition(p,copper,contacts,None)]
        union=p.SHAPE_POLY_SET()
        for cell in cells:union.Append(cell)
        union.Simplify()
        difference=p.SHAPE_POLY_SET(copper);difference.BooleanSubtract(union)
        outside=p.SHAPE_POLY_SET(union);outside.BooleanSubtract(copper)
        self.assertAlmostEqual(difference.Area()/1e12,0,places=8)
        self.assertAlmostEqual(outside.Area()/1e12,0,places=8)
        self.assertAlmostEqual(sum(c.Area() for c in cells)/1e12,copper.Area()/1e12,places=8)
        for index,cell in enumerate(cells):
            for other in cells[index+1:]:
                overlap=p.SHAPE_POLY_SET(cell);overlap.BooleanIntersection(other)
                self.assertAlmostEqual(overlap.Area()/1e12,0,places=8)
            for contact in contacts:
                inside=p.SHAPE_POLY_SET(cell);inside.BooleanIntersection(contact)
                # No cell may straddle an electrode boundary.
                self.assertTrue(abs(inside.Area())<1 or abs(inside.Area()-cell.Area())<1)

    def test_cancellation_is_preserved(self):
        from quick_pi_plugin.board_geometry import _partition
        with self.assertRaisesRegex(ValueError,'cancelled'):
            _partition(p,self.rectangle(0,0,10,10),[self.rectangle(1,1,1,1)],lambda *args:False)


if __name__=='__main__':unittest.main()
