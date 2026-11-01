"""Independent analytic angular patterns and missing-coverage contracts."""
import copy
import math
import unittest

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from quick_emerge_plugin.radiation_pattern import prepare_radiation,radiation_cut,radiation_status,CUTS
from quick_emerge_plugin import plots


def pattern(function=lambda theta,phi:1.,theta=None,phi=None):
    theta=np.linspace(0,math.pi,9) if theta is None else np.asarray(theta)
    phi=np.linspace(-math.pi,math.pi,17) if phi is None else np.asarray(phi)
    return dict(frequency_hz=2.4e9,theta_rad=theta.tolist(),phi_rad=phi.tolist(),
                norm_e=[[float(function(t,p)) for p in phi] for t in theta])


class RadiationPatternTests(unittest.TestCase):
    def test_isotropic_cuts_use_original_constant_samples(self):
        data=prepare_radiation(pattern())
        for name in CUTS:
            cut=radiation_cut(data,name)
            np.testing.assert_allclose(cut['relative_e'][np.isfinite(cut['relative_e'])],1)
            for row in cut['samples']:
                if row: self.assertEqual(row['relative_e'],data.relative[row['theta_index'],row['phi_index']])

    def test_dipole_principal_planes_and_azimuth_have_expected_orientation(self):
        data=prepare_radiation(pattern(lambda theta,phi:abs(math.sin(theta))))
        for name in ('XZ cut','YZ cut'):
            cut=radiation_cut(data,name); finite=np.isfinite(cut['angles_rad'])
            np.testing.assert_allclose(cut['relative_e'][finite],np.abs(np.sin(cut['angles_rad'][finite])),atol=1e-14)
        np.testing.assert_allclose(radiation_cut(data,'XY azimuth')['relative_e'],1)

    def test_asymmetric_pattern_uses_opposite_planes_and_global_not_cut_peak(self):
        data=prepare_radiation(pattern(lambda theta,phi:abs(math.sin(theta))*(1+.3*math.cos(phi))))
        self.assertAlmostEqual(data.peak,1.3)
        expected={'XZ cut':{0.:1.,180.:.7/1.3,-180.:.7/1.3},'YZ cut':{90.:1/1.3,-90.:1/1.3}}
        for name,values in expected.items():
            rows=[row for row in radiation_cut(data,name)['samples'] if row and abs(row['theta_deg']-90)<1e-8]
            self.assertEqual(len(rows),2)
            for row in rows: self.assertAlmostEqual(row['relative_e'],values[round(row['phi_deg'],7)])
        xy=radiation_cut(data,'XY azimuth')
        for row in xy['samples']:
            self.assertAlmostEqual(row['relative_e'],(1+.3*math.cos(math.radians(row['phi_deg'])))/1.3)

    def test_wrapped_phi_is_continuous_but_probe_angles_remain_original(self):
        raw=pattern(phi=np.radians([350,0,10]));before=copy.deepcopy(raw)
        data=prepare_radiation(raw);cut=radiation_cut(data,'XY azimuth')
        np.testing.assert_allclose(np.degrees(cut['angles_rad']),[350,360,370])
        np.testing.assert_allclose([row['phi_deg'] for row in cut['samples']],[350,0,10])
        self.assertEqual(raw,before)

    def test_duplicated_seam_is_one_plane_not_a_missing_opposite_half(self):
        data=prepare_radiation(pattern(phi=[-math.pi,math.pi]))
        cut=radiation_cut(data,'XZ cut')
        self.assertFalse(any(0<angle<math.pi and math.isfinite(value)
                             for angle,value in zip(cut['angles_rad'],cut['relative_e'])))
        self.assertIn('half not sampled',cut['caption'])
        with self.assertRaisesRegex(ValueError,'No known original samples'): radiation_cut(data,'YZ cut')

    def test_rotated_nearest_plane_is_declared_and_nonantipodal_half_stays_missing(self):
        data=prepare_radiation(pattern(phi=np.radians([-175,-85,5,95,185])))
        cut=radiation_cut(data,'XZ cut');self.assertIn('φ=5°',cut['caption'])
        self.assertTrue('φ=-175°' in cut['caption'] or 'φ=185°' in cut['caption'])
        data=prepare_radiation(pattern(phi=np.radians([10,200])))
        cut=radiation_cut(data,'XZ cut')
        self.assertIn('half not sampled',cut['caption'])
        self.assertFalse(any(row and abs(row['phi_deg']-200)<1e-7 for row in cut['samples']))

    def test_unknown_samples_and_unmeasured_poles_remain_gaps(self):
        raw=pattern(theta=np.radians([10,50,90,130,170]));raw['norm_e'][2][8]=None
        before=copy.deepcopy(raw);data=prepare_radiation(raw);cut=radiation_cut(data,'XZ cut')
        self.assertTrue(data.unknown);self.assertTrue(np.isnan(data.relative[2,8]))
        self.assertTrue(np.isnan(cut['relative_e']).any())
        self.assertFalse(any(row and row['theta_deg'] in (0,180) for row in cut['samples']))
        self.assertEqual(raw,before)
        figure=Figure();FigureCanvasAgg(figure)
        for renderer in (plots.radiation,plots.radiation_polar): renderer(figure,{'radiation':raw});figure.canvas.draw()

    def test_zero_missing_or_malformed_data_are_unavailable(self):
        for change in (dict(theta_rad=[0,float('nan')]),dict(theta_rad=[1,0]),dict(phi_rad=[1,0,-1]),
                       dict(norm_e=[[1,2]]),dict(frequency_hz=0),dict(frequency_hz=True)):
            raw=pattern();raw.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError): prepare_radiation(raw)
        for value in (-1,float('inf'),float('nan'),True,'1'):
            raw=pattern();raw['norm_e'][0][0]=value
            with self.subTest(value=value),self.assertRaises(ValueError): prepare_radiation(raw)
        raw=pattern(lambda theta,phi:0.)
        with self.assertRaisesRegex(ValueError,'No positive'): prepare_radiation(raw)
        self.assertEqual(prepare_radiation(raw,allow_zero=True).peak,0)
        self.assertIsNone(radiation_status({})[0])

    def test_polar_plot_conventions_and_global_radius_match_data(self):
        raw=pattern(lambda theta,phi:abs(math.sin(theta))*(1+.3*math.cos(phi)))
        data=prepare_radiation(raw);figure=Figure();FigureCanvasAgg(figure)
        for name in CUTS:
            plots.radiation_polar(figure,{'radiation':raw},{'radiation_cut':name});axes=figure.axes[0]
            self.assertEqual(axes.name,'polar');self.assertEqual(axes.get_ylim(),(0,1.05))
            self.assertEqual(axes.get_theta_direction(),1 if name=='XY azimuth' else -1)
            np.testing.assert_allclose(axes.lines[0].get_ydata(),radiation_cut(data,name)['relative_e'],equal_nan=True)
            self.assertIn('global stored-sample maximum',axes.get_title())


if __name__=='__main__': unittest.main()
