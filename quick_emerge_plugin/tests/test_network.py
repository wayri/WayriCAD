"""Independent analytical oracles for real-reference sampled networks."""
import unittest
import numpy as np
from numpy.testing import assert_allclose
from quick_emerge_plugin.network import SampledNetwork, from_result


class NetworkTests(unittest.TestCase):
    def test_one_port_matched_open_short_and_load(self):
        matched=SampledNetwork([1e9],[[[0]]])
        assert_allclose(matched.to_z(),[[[50]]])
        assert_allclose(matched.to_y(),[[[.02]]])
        a=matched.analyze()
        self.assertTrue(np.isposinf(a['return_loss_db'][0,0]))
        assert_allclose(a['input_impedance_ohm'],[[50]])
        self.assertEqual(a['vswr'][0,0],1)
        load=SampledNetwork([1e9],[[[1/3]]])
        assert_allclose(load.to_z(),[[[100]]])
        assert_allclose(load.renormalize(100).s,0,atol=1e-15)
        open_circuit=SampledNetwork([1e9],[[[1]]])
        with self.assertRaisesRegex(ValueError,'singular'):
            open_circuit.to_z()
        assert_allclose(open_circuit.to_y(),0)
        short=SampledNetwork([1e9],[[[-1]]])
        assert_allclose(short.to_z(),0)
        with self.assertRaisesRegex(ValueError,'singular'):
            short.to_y()

    def test_unequal_real_references_against_physical_z(self):
        z=np.array([[[80,20],[20,120]]],complex)
        refs=np.array([25,75])
        n=SampledNetwork.from_z([1e9],z,refs,['left','right'])
        # Independently solve V=D(a+b), I=D^-1(a-b) with ZI=V.
        d=np.diag(np.sqrt(refs)); dinv=np.linalg.inv(d)
        expected=np.linalg.solve(d+z[0]@dinv,z[0]@dinv-d)
        assert_allclose(n.s[0],expected,atol=1e-14)
        assert_allclose(n.to_z(),z,atol=1e-12)
        assert_allclose(n.to_y(),np.linalg.inv(z),atol=1e-14)
        assert_allclose(SampledNetwork.from_y([1e9],np.linalg.inv(z),refs).s,n.s,atol=1e-14)
        assert_allclose(n.renormalize([50,100]).to_z(),z,atol=1e-12)
        self.assertEqual(n.port_names,('left','right'))

    def test_ideal_thru_renormalization_does_not_require_z(self):
        n=SampledNetwork([1e9],[[[0,1],[1,0]]])
        with self.assertRaises(ValueError):
            n.to_z()
        assert_allclose(n.renormalize(75).s,n.s,atol=1e-14)
        transformed=n.renormalize([25,100])
        # Ideal zero-length junction between unequal reference impedances.
        assert_allclose(transformed.s,[[[.6,.8],[.8,-.6]]],atol=1e-14)
        assert_allclose(transformed.renormalize(50).s,n.s,atol=1e-14)

    def test_known_phase_delay_nonuniform_grid_and_zeros(self):
        f=np.array([1,1.03,1.11,1.19])*1e9
        tau=2e-9
        s=np.zeros((len(f),2,2),complex)
        s[:,0,1]=s[:,1,0]=np.exp(-2j*np.pi*f*tau)
        a=SampledNetwork(f,s).analyze()
        assert_allclose(a['group_delay_s'][:,1,0],tau,rtol=1e-12)
        self.assertTrue(np.isnan(a['group_delay_s'][:,0,0]).all())
        self.assertTrue(np.isneginf(a['magnitude_db'][:,0,0]).all())
        self.assertTrue(a['sampled_passive']); self.assertTrue(a['sampled_reciprocal'])

    def test_phase_is_not_unwrapped_across_unknown_zero(self):
        s=np.exp(1j*np.array([0,.1,.2,.3,.4]))[:,None,None]
        s[2,0,0]=0
        a=SampledNetwork(np.arange(1,6),s).analyze()
        self.assertTrue(np.isnan(a['phase_rad'][2,0,0]))
        self.assertTrue(np.isnan(a['group_delay_s'][2,0,0]))
        assert_allclose(a['group_delay_s'][[0,1,3,4],0,0],-.1/(2*np.pi))

    def test_passivity_svd_detects_null_start_and_reciprocity(self):
        n=SampledNetwork([1],[[[.6,-.6],[-.6,.6]]])
        a=n.analyze()
        assert_allclose(a['largest_singular_value'],[1.2])
        self.assertFalse(a['sampled_passive'])
        self.assertTrue(a['sampled_reciprocal'])
        a=SampledNetwork([1],[[[0,.1],[.2,0]]]).analyze()
        assert_allclose(a['reciprocity_error'],.1)
        self.assertFalse(a['sampled_reciprocal'])

    def test_loaded_reduction_against_independent_admittance_oracle(self):
        y=np.array([[[.04,-.02,-.01],[-.02,.05,-.01],[-.01,-.01,.04]]])
        n=SampledNetwork.from_y([1e9],y,50,['a','b','aux'])
        red=n.terminate(['a','b'],{'aux':50})
        expected=[[[.038333333333333333,-.021666666666666667],[-.021666666666666667,.04833333333333333]]]
        assert_allclose(red.to_y(),expected,atol=1e-15)
        assert_allclose(n.terminate(['b','a'],{'aux':50}).to_y(),np.array(expected)[:,::-1,::-1],atol=1e-15)
        self.assertEqual(red.provenance['transformations'][0]['loads_ohm'],{'aux':50})
        self.assertEqual(red.provenance['origin_network_sha256'],n.digest())

    def test_load_through_open_short_and_resistor(self):
        thru=SampledNetwork([1],[[[0,1],[1,0]]])
        for load,gamma in [('open',1),('short',-1),(100,1/3),(50,0)]:
            with self.subTest(load=load):
                assert_allclose(thru.terminate([0],{1:load}).s,[[[gamma]]],atol=1e-14)
        resonator=SampledNetwork([1],[[[0,0],[0,1]]])
        with self.assertRaisesRegex(ValueError,'singular'):
            resonator.terminate([0],{1:'open'})

    def test_mixed_mode_power_transform_and_polarity(self):
        # Two uncoupled equal thru lines, physical order [in+,in-,out+,out-].
        s=np.zeros((1,4,4)); s[0,0,2]=s[0,2,0]=s[0,1,3]=s[0,3,1]=1
        n=SampledNetwork([1],s)
        mixed=n.mixed_mode([(0,1),(2,3)])
        expected=np.zeros((1,4,4)); expected[0,0,1]=expected[0,1,0]=expected[0,2,3]=expected[0,3,2]=1
        assert_allclose(mixed.s,expected,atol=1e-15)
        assert_allclose(mixed.z0_ohm,[100,100,25,25])
        self.assertEqual(mixed.port_names,('d(P1,P2)','d(P3,P4)','c(P1,P2)','c(P3,P4)'))
        assert_allclose(np.linalg.svd(mixed.s,compute_uv=False),np.linalg.svd(n.s,compute_uv=False),atol=1e-15)
        reversed_pair=n.mixed_mode([(0,1),(3,2)])
        self.assertAlmostEqual(reversed_pair.s[0,0,1],-1)
        three=SampledNetwork([1],np.zeros((1,3,3))).mixed_mode([(1,0)])
        self.assertEqual(three.port_names[-1],'P3')

    def test_invalid_data_loads_pairs_and_immutability(self):
        for f,s,z,names in [([0],[[[0]]],50,None),([2,1],[[[0]],[[0]]],50,None),
                             ([1],[[[complex(float('nan'))]]],50,None),([1],[[[0]]],-1,None),
                             ([True],[[[0]]],50,None),([1],[[[True]]],50,None),
                             ([1],[[[0,0],[0,0]]],50,['x','x']),([1],[[[0]]],True,None)]:
            with self.subTest(f=f,s=s,z=z), self.assertRaises(ValueError):
                SampledNetwork(f,s,z,names)
        n=SampledNetwork([1],[[[0,1],[1,0]]])
        for keep,loads in [([0],{}),([0],{0:50}),([0],{1:0}),([0],{1:float('inf')}),([0,0],{}),([],{}),([0],{1:True})]:
            with self.subTest(keep=keep,loads=loads),self.assertRaises(ValueError):
                n.terminate(keep,loads)
        for pairs in [[],[(0,0)],[(0,1),(1,0)],[(0,2)]]:
            with self.subTest(pairs=pairs),self.assertRaises(ValueError):
                n.mixed_mode(pairs)
        with self.assertRaises(ValueError):
            n.renormalize([50,0])
        with self.assertRaises(ValueError):
            n.renormalize(np.array([50+1j,50]))
        with self.assertRaises(ValueError):
            n.terminate([0],{1:np.array(50+1j)})
        with self.assertRaises(ValueError):
            SampledNetwork([1],[[[0]]],50,'x')
        with self.assertRaises(ValueError):
            n.renormalize([25,50]).mixed_mode([(0,1)])
        with self.assertRaises(ValueError):
            n.s[0,0,0]=10

    def test_result_receiver_source_order_and_missing_entries(self):
        result={'schema':1,'port_count':2,'config':{'z0_ohm':50},'frequencies_hz':[1],
                's_parameters':{'S11':[[0,0]],'S12':[[.8,-.1]],'S21':[[.79,-.09]],'S22':[[0,0]]}}
        n=from_result(result)
        self.assertEqual(n.s[0,0,1],.8-.1j)
        self.assertEqual(n.s[0,1,0],.79-.09j)
        del result['s_parameters']['S21']
        with self.assertRaises(ValueError):from_result(result)


if __name__=='__main__':unittest.main()
