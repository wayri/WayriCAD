"""References for original-volume quantities and linked native workbench views."""
import copy
import math
import unittest
from quick_emerge_plugin.field_display import field_for_display, volume_samples
from quick_emerge_plugin.inspection import FieldInspection

class FieldDisplayTests(unittest.TestCase):
    def setUp(self):
        self.raw={'x_mm':[1,3],'y_mm':[2,5],'z_mm':4,'frequency_hz':2e9,
                  'norm_e_v_m':[[math.sqrt(5)]*2 for _ in range(2)],
                  'e_real_v_m':[[[2]*2 for _ in range(2)],[[0]*2 for _ in range(2)],[[0]*2 for _ in range(2)]],
                  'e_imag_v_m':[[[1]*2 for _ in range(2)],[[0]*2 for _ in range(2)],[[0]*2 for _ in range(2)]],
                  'h_real_a_m':[[[0]*2 for _ in range(2)],[[3]*2 for _ in range(2)],[[0]*2 for _ in range(2)]],
                  'h_imag_a_m':[[[0]*2 for _ in range(2)],[[-4]*2 for _ in range(2)],[[0]*2 for _ in range(2)]]}
        volume={k:([v,v] if k=='norm_e_v_m' else [[component,component] for component in v]) for k,v in self.raw.items() if k.startswith(('norm_','e_','h_'))}
        volume.update(x_mm=[1,3],y_mm=[2,5],z_mm=[.5,4]);self.raw['volume']=volume
        self.result={'field':self.raw}
    def test_complex_vector_units_and_original_custody(self):
        before=copy.deepcopy(self.result)
        h=field_for_display(self.result,'H magnitude')
        self.assertEqual(h['display_unit'],'A/m');self.assertAlmostEqual(h['display_values'][0][0],5)
        p=field_for_display(self.result,'Power-flow magnitude')
        self.assertEqual(p['display_unit'],'W/m2');self.assertAlmostEqual(p['display_values'][0][0],1)
        self.assertEqual(self.result,before)
    def test_volume_slice_and_identity(self):
        field=field_for_display(self.result,'H magnitude',0);probe=FieldInspection(field).probe(1,2)
        self.assertEqual((probe['z_mm'],probe['iz'],probe['value_a_m']),(.5,0,5))
        rows=volume_samples(field);self.assertEqual(len(rows),8)
        self.assertEqual((rows[-1]['x_mm'],rows[-1]['y_mm'],rows[-1]['z_mm'],rows[-1]['iz']),(3,5,4,1))
        with self.assertRaises(ValueError):field_for_display(self.result,'E magnitude',True)
    def test_volume_slice_uses_its_own_original_xy_coordinates(self):
        self.raw['volume'].update(x_mm=[10,20],y_mm=[30,40])
        before=copy.deepcopy(self.result)
        field=field_for_display(self.result,'E magnitude',0)
        row=FieldInspection(field).probe(10,30)
        self.assertEqual((row['x_mm'],row['y_mm'],row['ix'],row['iy']),(10,30,0,0))
        self.assertEqual(self.result,before)

    def test_sampling_labels_count_stored_axes_and_largest_spacing(self):
        from quick_emerge_plugin.field_display import plane_sampling_label,angular_sampling_label
        label=plane_sampling_label({'x_mm':[0,1,3],'y_mm':[0,4]})
        self.assertIn('3×2 original samples',label);self.assertIn('Δx ≤ 2 mm',label)
        self.assertIn('Δy ≤ 4 mm',label)
        label=angular_sampling_label({'theta_rad':[0,math.pi/2,math.pi],'phi_rad':[-math.pi,0,math.pi]})
        self.assertIn('3×3 stored angular samples',label)
        self.assertIn('Δθ ≤ 90°',label);self.assertIn('Δφ ≤ 180°',label)

    def test_thermal_has_no_invented_frequency_or_em_units(self):
        self.result['thermal']={'x_mm':[1,3],'y_mm':[2,5],'z_mm':-.001,'temperature_k':[[300,301],[302,303]],'time_s':2}
        thermal=field_for_display(self.result,'Temperature');row=FieldInspection(thermal).probe(1,2)
        self.assertNotIn('frequency_hz',row);self.assertNotIn('value_v_m',row)
        self.assertEqual((row['temperature_k'],row['unit'],row['time_s']),(300,'K',2))
        self.assertEqual(field_for_display(self.result,'E magnitude')['display_unit'],'V/m')
    def test_unknown_vector_does_not_become_zero(self):
        self.raw['h_imag_a_m'][1][0][0]=None
        self.assertIsNone(field_for_display(self.result,'H magnitude')['display_values'][0][0])

if __name__=='__main__':unittest.main()
