"""Pad geometry drives advisory families; filters never choose a new route."""
import unittest
from wayricad_runtime.fanout_families import FAMILIES,observed_family,styles_for,guidance
from wayricad_runtime.fanout_profiles import FANOUT_PATTERNS
import test_perimeter_expansion as perimeter
import test_connector_escape as connector
p=perimeter.p


class FamilyVocabularyTests(unittest.TestCase):
    def test_every_style_has_one_family_and_filter_preserves_current(self):
        listed=[style for styles in FAMILIES.values() for style in styles]
        self.assertEqual(set(listed),set(FANOUT_PATTERNS));self.assertEqual(len(listed),len(set(listed)))
        for family in FAMILIES:
            self.assertIn('Connector edge',styles_for(family,'Connector edge'))


@unittest.skipIf(p is None,'Native KiCad required')
class NativeFamilyTests(unittest.TestCase):
    def test_rotated_perimeter_and_pth_are_classified_without_part_names(self):
        for rotation in (0,37,90):
            board,fp=perimeter.PerimeterExpansionTests().fixture(qfp=True,rotation=rotation)
            fp.SetReference('J_BGA')
            self.assertEqual(observed_family(fp,p)[0],'QFP/QFN / perimeter')
        fixture=connector.ConnectorTests();fixture.setUp();fixture.connector()
        fixture.fp.SetReference('U_QFN')
        self.assertEqual(observed_family(fixture.fp,p)[0],'Connector / SMT or plated THT')
        self.assertIn('outside this family',guidance(fixture.fp,p,'Staggered rows'))

    def test_populated_grid_and_irregular_array_are_distinct(self):
        fixture=connector.ConnectorTests();fixture.setUp()
        for i in range(3):
            for j in range(3):fixture.pad(f'N{i}{j}',18+i,18+j)
        fixture.fp.SetReference('J_QFP');fixture.fp.SetOrientationDegrees(37)
        self.assertEqual(observed_family(fixture.fp,p)[0],'BGA/LGA / grid')
        pad=next(iter(fixture.fp.Pads()));pad.SetPosition(perimeter.PerimeterExpansionTests.xy(23.7,24.3))
        self.assertIsNone(observed_family(fixture.fp,p)[0])


if __name__=='__main__':unittest.main()
