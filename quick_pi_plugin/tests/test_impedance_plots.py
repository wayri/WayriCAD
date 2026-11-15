import copy
import math
import unittest
from quick_pi_plugin.impedance_plots import samples,matched_differences,draw_magnitudes,probe_text


def dataset():
    return {'units':{'frequency':'Hz','impedance':'ohm'},'frequencies':[
        {'frequency_hz':f,'z_ohm':[[{'real':r,'imag':1.} for r in (2.,.5)] for _ in range(2)]}
        for f in (1e6,1e7,1e8)]}


class ImpedancePlotTests(unittest.TestCase):
    def test_exact_matches_take_priority_in_dense_sweep(self):
        current,reference=dataset(),dataset()
        frequencies=[1e9,1e9+.5,1e9+1.]
        for i,f in enumerate(frequencies):
            current['frequencies'][i]['frequency_hz']=f
            reference['frequencies'][i]['frequency_hz']=f
            for line in reference['frequencies'][i]['z_ohm']:
                for value in line:
                    value['real']*=i+1;value['imag']*=i+1
        f,delta=matched_differences(current,reference,0)
        self.assertEqual(f,frequencies)
        for i,difference in enumerate(delta):
            self.assertAlmostEqual(difference,-20*math.log10(i+1))
        self.assertEqual(matched_differences(current,current,0),(frequencies,[0.,0.,0.]))

    def test_tolerant_matching_still_rejects_ambiguous_or_unsampled_points(self):
        current,reference=dataset(),dataset()
        current['frequencies']=current['frequencies'][:1]
        current['frequencies'][0]['frequency_hz']=1e9+.25
        reference['frequencies']=reference['frequencies'][:2]
        for row,f in zip(reference['frequencies'],[1e9,1e9+.5]):
            row['frequency_hz']=f
        self.assertEqual(matched_differences(current,reference,0),([],[]))
        reference['frequencies']=reference['frequencies'][:1]
        self.assertEqual(matched_differences(current,reference,0)[0],[1e9+.25])
        current['frequencies'][0]['frequency_hz']=1e9+2.
        self.assertEqual(matched_differences(current,reference,0),([],[]))

    def test_rejects_unrepresentable_magnitude_but_keeps_large_finite_and_zero(self):
        data=dataset()
        entry=data['frequencies'][0]['z_ohm'][0][0]
        entry.update(real=1.7e308,imag=1.7e308)
        with self.assertRaisesRegex(ValueError,'magnitudes'):
            samples(data)
        entry.update(real=1e308,imag=1e308)
        self.assertTrue(math.isfinite(abs(samples(data)[1][0][0])))
        entry.update(real=0.,imag=0.)
        self.assertEqual(samples(data)[1][0][0],0j)

    def test_probe_log_distance_handles_extreme_frequency_ranges(self):
        axis=object()
        probes={axis:[('sample',[1e-300,1e-100],[1j,2j])]}
        self.assertIn('1e-100 Hz',probe_text(probes,axis,1e300))
        probes={axis:[('sample',[1e100,1e300],[1j,2j])]}
        self.assertIn('1e+100 Hz',probe_text(probes,axis,1e-300))
        for frequency in (float('nan'),float('inf'),0.,-1.,None):
            self.assertEqual(probe_text(probes,axis,frequency),'')

    def test_signed_difference_uses_magnitude_ratio_and_only_matching_samples(self):
        current,reference=dataset(),dataset()
        for row in reference['frequencies']:
            for line in row['z_ohm']:
                for value in line:value['real']*=2;value['imag']*=2
        f,delta=matched_differences(current,reference,0)
        self.assertEqual(f,[1e6,1e7,1e8])
        for difference in delta:self.assertAlmostEqual(difference,-20*math.log10(2))
        reference['frequencies'][1]['frequency_hz']=2e7
        self.assertEqual(matched_differences(current,reference,0)[0],[1e6,1e8])

    def test_rejects_malformed_units_order_and_nonfinite_data(self):
        for change in ('units','order','nan','row'):
            data=dataset()
            if change=='units':data['units']=None
            elif change=='order':data['frequencies'].reverse()
            elif change=='row':data['frequencies'][0]=None
            else:data['frequencies'][0]['z_ohm'][0][0]['real']=float('nan')
            with self.assertRaises(ValueError):samples(data)

    def test_oversized_json_integers_are_validation_errors_not_overflows(self):
        for field in ('frequency','impedance'):
            data=dataset()
            if field=='frequency':data['frequencies'][0]['frequency_hz']=10**400
            else:data['frequencies'][0]['z_ohm'][0][0]['real']=10**400
            with self.assertRaises(ValueError):samples(data)
        axis=object()
        self.assertEqual(probe_text({axis:[('sample',[1.],[1j])]},axis,10**400),'')

    def test_actual_plot_axes_and_nearest_sample_probes(self):
        from matplotlib.figure import Figure
        data=dataset();before=copy.deepcopy(data)
        figure=Figure();probes=draw_magnitudes(figure,data)
        self.assertEqual(len(figure.axes),4)
        for axis in figure.axes:
            self.assertEqual(axis.get_xscale(),'log');self.assertEqual(axis.get_yscale(),'log')
            self.assertIn('ohm',axis.get_ylabel())
        text=probe_text(probes,figure.axes[0],1.1e7)
        self.assertIn('10000000 Hz',text);self.assertIn('phase=',text)
        figure.clear();draw_magnitudes(figure,data,data,'Actual imported reference')
        self.assertEqual(len(figure.axes),8)
        self.assertEqual(data,before)
