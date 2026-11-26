import copy
import unittest

from quick_pi_plugin.pinned_probes import callout_positions, reading
from quick_pi_plugin.tests.test_report import bundle
from quick_pi_plugin.differential_probe import sample_point


class PinnedProbeTests(unittest.TestCase):
    def test_same_coordinates_recompute_after_remeshing_or_rerun(self):
        baseline=bundle()
        first=next(iter(baseline['mesh']['triangle_layer']))
        probe=dict(layer=first, point=(3.25,.4))
        original=reading(baseline,probe,'voltage')
        self.assertIsNotNone(original)
        check=sample_point(baseline,first,*probe['point'],check_source=False)
        self.assertAlmostEqual(original['value'],check['potential_V'])
        revised=copy.deepcopy(baseline)
        revised['mesh']['triangles'].reverse()
        revised['result']['potential_V']=[value*2 if value is not None else None
                                           for value in revised['result']['potential_V']]
        self.assertAlmostEqual(reading(revised,probe,'voltage')['value'],2*original['value'])
        self.assertIsNone(reading(revised,dict(probe,net='different rail'),'voltage'))

    def test_clustered_callouts_move_instead_of_overlapping(self):
        a,b,c=callout_positions([(100,100),(102,103),(500,500)],[(60,20)]*3,(0,0,220,200),1)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertIsNone(c)
        self.assertNotEqual(a,b)
