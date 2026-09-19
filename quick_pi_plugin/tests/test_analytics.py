"""Layer thickness, physical loss allocation and local-screen regressions."""
import unittest
from quick_pi_plugin.solver import solve
from quick_pi_plugin.analytics import details_text
from quick_pi_plugin.tests.test_solver import strip,combine


class AnalyticsTests(unittest.TestCase):
    def test_doubled_actual_copper_thickness_halves_r_loss_and_j(self):
        outputs=[]
        for thickness in (.035,.070):
            mesh,source,sink=strip(thickness=thickness)
            outputs.append(solve(mesh,source,sink,sink_current=2,options={'pulse_duration_s':1}))
        thin,thick=outputs
        for key in ('drop_over_current_ohm','total_power_W','max_current_density_A_mm2'):
            self.assertAlmostEqual(thin[key],2*thick[key],places=10)
        a=thin['analytics']['layers'][0];b=thick['analytics']['layers'][0]
        self.assertAlmostEqual(a['area_mm2'],10)
        self.assertAlmostEqual(a['volume_mm3'],.35)
        self.assertAlmostEqual(b['volume_mm3'],.7)
        self.assertEqual(b['thickness_min_mm'],.070)
        # At equal current, doubling thickness halves loss and doubles thermal mass.
        self.assertAlmostEqual(thin['analytics']['hotspots_by_heating_density'][0]['thermal']['energy_ratio'],
                               4*thick['analytics']['hotspots_by_heating_density'][0]['thermal']['energy_ratio'],places=10)

    def test_layer_via_component_accounting_and_ranked_coordinates(self):
        a,sa,ta=strip();b,sb,tb=strip(z=1.6,thickness=.07)
        mesh,n=combine(a,b)
        mesh['vias']=[{'id':'v1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                       'length_mm':1.6,'drill_mm':.3,'plating_mm':.025,'top_layer':0,'bottom_layer':1.6}]
        result=solve(mesh,sa,[i+n for i in tb],sink_current=2)
        analysis=result['analytics'];loss=analysis['losses']
        self.assertAlmostEqual(loss['planar_W']+loss['via_W']+loss['component_W'],result['total_power_W'],places=12)
        self.assertAlmostEqual(loss['via_W'],result['vias'][0]['power_W'],places=12)
        self.assertEqual(len(analysis['layers']),2)
        self.assertLess(loss['accounting_error_W'],1e-12)
        for row in analysis['hotspots_by_heating_density']:
            self.assertEqual(len(row['location_mm']),3)
            self.assertIsNone(row['thermal']['energy_ratio'])
        text=details_text(result)
        self.assertIn('Via barrels',text)
        self.assertIn('pulse duration required',text)
        self.assertIn('not',analysis['notice'])

    def test_floating_copper_is_not_reported_as_connected_area(self):
        a,source,sink=strip();b,_,_=strip(z=1)
        mesh,_=combine(a,b)
        result=solve(mesh,source,sink)
        floating=result['analytics']['layers'][1]
        self.assertAlmostEqual(floating['area_mm2'],10)
        self.assertEqual(floating['connected_area_mm2'],0)
        self.assertEqual(floating['planar_power_W'],0)
        self.assertIsNone(floating['peak_current_density_A_mm2'])

    def test_component_loss_is_not_counted_as_copper(self):
        a,sa,ta=strip();b,sb,tb=strip(z=1)
        mesh,n=combine(a,b)
        mesh['lumped_branches']=[{'id':'R1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                                 'resistance_ohm':.1,'inductance_h':.005}]
        result=solve(mesh,sa,[i+n for i in tb],sink_current=2)
        loss=result['analytics']['losses']
        self.assertAlmostEqual(loss['component_W'],.4,places=10)
        self.assertAlmostEqual(loss['planar_W'],result['conductor_power_W'],places=10)
        self.assertEqual(loss['via_W'],0)
        self.assertAlmostEqual(loss['total_W'],result['total_power_W'],places=10)


if __name__=='__main__':unittest.main()
