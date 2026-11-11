"""Analytical contracts for coupled FEM arrays; synthetic matrices are not FEM solves."""
import copy
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np
from numpy.testing import assert_allclose

from quick_emerge_plugin.fem_array import excitation, fem_aesa_config, power_accounting
from quick_emerge_plugin.model import config_digest, validate_config
from quick_emerge_plugin.network import SampledNetwork, from_result
from quick_emerge_plugin.network_extensions import serialize_network, deserialize_network
from quick_emerge_plugin.network_keys import s_key


class FEMArrayTests(unittest.TestCase):
    def test_fem_presets_have_physical_ports_not_analytical_dispatch(self):
        for nx,ny in [(2,1),(2,2),(4,4)]:
            c=fem_aesa_config(nx,ny,30,20,'binomial')
            self.assertEqual(c['advanced']['study'],'array')
            self.assertEqual(c['advanced']['array_count_x']*c['advanced']['array_count_y'],nx*ny)
            self.assertEqual(c['points'],3)
        for nx,ny in [(1,1),(5,1),(True,2),(2.5,2)]:
            with self.assertRaises(ValueError): fem_aesa_config(nx,ny)

    def test_reject_oversized_overlapping_out_of_board_and_nonfinite(self):
        c=fem_aesa_config(4,4)
        for changes in [dict(points=82),dict(substrate_x_mm=140),
                        dict(advanced={**c['advanced'],'export_optycal':True}),
                        dict(advanced={**c['advanced'],'array_count_y':5}),
                        dict(advanced={**c['advanced'],'array_pitch_x_mm':30}),
                        dict(advanced={**c['advanced'],'scan_theta_deg':float('nan')})]:
            with self.assertRaises(ValueError): validate_config({**c,**changes})

    def test_steering_phase_sign_and_fixed_frequency(self):
        c=fem_aesa_config(2,1,30)
        c['advanced']['array_pitch_x_mm']=299792458/3e9/2*1000
        c['substrate_x_mm']=120
        weights,meta=excitation(validate_config(c))
        self.assertAlmostEqual(meta['progressive_phase_x_deg'],-90)
        self.assertAlmostEqual(np.angle(weights[1]/weights[0]),-math.pi/2)
        self.assertEqual(meta['phase_reference_frequency_hz'],3e9)
        self.assertIn('fixed phase',meta['steering_model'])

    def test_tapers_normalize_incident_power_and_global_phase(self):
        for taper in ('uniform','binomial'):
            c=fem_aesa_config(4,4,35,70,taper)
            weights,_=excitation(c)
            self.assertAlmostEqual(float(np.vdot(weights,weights).real),1)
            stronger=copy.deepcopy(c); stronger['advanced']['array_power_w']=4
            assert_allclose(excitation(stronger)[0],2*weights)
            if taper=='binomial':
                assert_allclose(np.abs(weights).reshape(4,4)/abs(weights[0]),[[1,3,3,1],[3,9,9,3],[3,9,9,3],[1,3,3,1]])
        c=fem_aesa_config(2,1); c['advanced'].update(array_excitation_mode='progressive_phase',array_phase_x_deg=60)
        weights,_=excitation(c)
        self.assertAlmostEqual(np.angle(weights[1]/weights[0]),math.pi/3)

    def test_active_coupling_power_zero_driven_ports_and_no_clamps(self):
        for matrix,weights,accepted in [(np.zeros((2,2)),[1,0],1),
                                        (.5*np.eye(2),[1,1],1.5),
                                        (np.array([[0,1],[1,0]]),[1,.1],0)]:
            network=SampledNetwork([3e9],[matrix])
            row=power_accounting(network,weights)[0]
            self.assertAlmostEqual(row['accepted_power_w'],accepted)
            self.assertAlmostEqual(sum(row['per_port_net_power_w']),accepted)
            assert_allclose(power_accounting(network,np.array(weights)*1j)[0]['per_port_net_power_w'],row['per_port_net_power_w'])
        self.assertIsNone(power_accounting(SampledNetwork([3e9],[np.eye(2)]),[1,0])[0]['active_reflection_ri'][1])
        row=power_accounting(SampledNetwork([3e9],[[[0,1],[1,0]]]),[1,.1])[0]
        self.assertAlmostEqual(row['active_reflection_ri'][1][0],10)
        row=power_accounting(SampledNetwork([3e9],[2*np.eye(2)]),[1,0])[0]
        self.assertEqual(row['accepted_power_w'],-3)
        self.assertTrue(row['negative_total_accepted_power'])
        with self.assertRaises(ValueError): power_accounting(SampledNetwork([3e9],[np.eye(2)]),[0,0])

    def test_all_256_entries_roundtrip_without_collisions(self):
        values=np.arange(256).reshape(1,16,16)+1j*np.arange(256,512).reshape(1,16,16)
        network=SampledNetwork([3e9],values)
        payload=serialize_network(network)
        self.assertEqual(len(payload['s_parameters']),256)
        self.assertNotEqual(s_key(1,11),s_key(11,1))
        self.assertIn('S11',payload['s_parameters'])
        self.assertIn('S1_11',payload['s_parameters'])
        assert_allclose(deserialize_network(payload).s,values)
        assert_allclose(from_result({**payload,'config':{'z0_ohm':50}}).s,values)
        bad=copy.deepcopy(payload); bad['s_parameters']['S111']=bad['s_parameters'].pop('S1_11')
        with self.assertRaises(ValueError): deserialize_network(bad)

    def test_sixteen_port_touchstone_orders_every_entry(self):
        from quick_emerge_plugin.backend import write_touchstone
        values=np.arange(256).reshape(1,16,16)+0j
        result={**serialize_network(SampledNetwork([3e9],values)),'config':{'mode':'patch','z0_ohm':50},'reference_impedance_ohm':50}
        with tempfile.TemporaryDirectory() as folder:
            write_touchstone(folder,result)
            line=(Path(folder)/'network.s16p').read_text().splitlines()[-1].split()
        self.assertEqual(float(line[0]),3e9)
        self.assertEqual(len(line),513)
        assert_allclose(np.array(line[1:],float).reshape(16,16,2)[:,:,0],values[0].real)

    def test_legacy_digest_and_new_excitation_custody(self):
        c=fem_aesa_config()
        c['advanced']['array_excitation_mode']='progressive_phase'
        legacy=copy.deepcopy(c)
        legacy['advanced'].pop('array_excitation_mode'); legacy['advanced'].pop('array_taper')
        self.assertEqual(config_digest(c),config_digest(legacy))
        changed=copy.deepcopy(c); changed['advanced']['array_taper']='binomial'
        self.assertNotEqual(config_digest(c),config_digest(changed))

    def test_cli_writes_fem_not_ideal_setup(self):
        from quick_emerge_plugin.__main__ import main
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()):
            path=Path(folder)/'aesa.json'
            self.assertEqual(main(['--write-fem-aesa-setup',str(path),'--array-x','4','--array-y','4','--array-theta','30','--array-taper','binomial']),0)
            config=json.loads(path.read_text())['config']
            self.assertEqual(config['advanced']['study'],'array')
            self.assertEqual(config['advanced']['array_count_x'],4)
            self.assertEqual(config['advanced']['scan_theta_deg'],30)

    def test_report_contains_active_power_and_rejects_tampering(self):
        from quick_emerge_plugin.model import source_identity
        from quick_emerge_plugin.reporting import build_html_report, validate_report_result
        c=fem_aesa_config(4,4,30)
        weights,metadata=excitation(c)
        matrix=np.stack([.2*np.eye(16)]*3).astype(complex)
        net=SampledNetwork([2.9e9,3e9,3.1e9],matrix)
        result={**serialize_network(net),'config':c,'config_sha256':config_digest(c),
                'model_scope':'finite-patch-array-template',
                'source':source_identity(Path(__file__).parent/'fixtures/region_coupon.kicad_pcb'),
                'backend':{'backend':'Synthetic matrix fixture; not a FEM solve','version':'test'},
                'assumptions':['Synthetic network for report contract testing, not field evidence'],
                'array':{**metadata,'excitation_weights':[[float(v.real),float(v.imag)] for v in weights],
                         'power_accounting':power_accounting(net,weights)}}
        html=build_html_report(result,include_figures=False)
        self.assertIn('Coupled FEM array excitation',html)
        self.assertIn('S1_11',html)
        self.assertIn('S11_1',html)
        rounded=copy.deepcopy(result)
        rounded['array']['power_accounting'][0]['accepted_power_w']+=1e-12
        rounded['array']['excitation_weights'][0][0]+=1e-13
        validate_report_result(rounded)
        for change in ('accepted_power_w','excitation_weights'):
            bad=copy.deepcopy(result)
            if change=='accepted_power_w':bad['array']['power_accounting'][0][change]+=1
            else:bad['array'][change][0][0]+=1
            with self.assertRaisesRegex(ValueError,'excitation or active-power'):
                validate_report_result(bad)

    def test_array_ports_plot_has_scales_and_units(self):
        from matplotlib.figure import Figure
        from quick_emerge_plugin.plots import array_ports
        c=fem_aesa_config(2,1,30)
        weights,metadata=excitation(c)
        net=SampledNetwork([2.9e9,3e9,3.1e9],np.stack([.2*np.eye(2)]*3))
        result={**serialize_network(net),'config':c,'array':{**metadata,
                'excitation_weights':[[float(v.real),float(v.imag)] for v in weights]}}
        figure=Figure();array_ports(figure,result)
        self.assertEqual(figure.axes[0].get_ylabel(),'Active reflection [dB]')
        self.assertEqual(figure.axes[1].get_ylabel(),'Power [W]')
        self.assertEqual(figure.axes[1].get_xlabel(),'Frequency [GHz]')


if __name__=='__main__': unittest.main()
