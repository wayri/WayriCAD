import math
import unittest
from unittest.mock import patch
from planar_magnetics_plugin.motor_model import *

class MotorTests(unittest.TestCase):
    def model(self,kind='rotary'):
        return build_motor(synthesize_winding(36,4,3,9,turns_per_coil=10),kind=kind,fundamental_b_t=.5,active_length_mm=50,**({'airgap_radius_mm':20} if kind=='rotary' else {'pole_pitch_mm':30}))
    def test_standard_distributed_and_concentrated_factors(self):
        w=synthesize_winding(36,4,3,9)
        expected=math.sin(math.radians(30))/(3*math.sin(math.radians(10)))
        self.assertEqual(w['status'],'BALANCED')
        for p in w['phase_data']:self.assertAlmostEqual(p['kw'],expected,places=12)
        tooth=synthesize_winding(12,10,3,1,style='concentrated')
        self.assertEqual(tooth['status'],'BALANCED')
        self.assertAlmostEqual(tooth['phase_data'][0]['kw'],.9330127018922193,places=12)
        short=synthesize_winding(36,4,3,8,style='chorded')
        self.assertEqual(short['status'],'BALANCED')
        self.assertLess(short['phase_data'][0]['kw'],expected)
    def test_two_phase_and_five_phase(self):
        for slots,poles,m,pitch,step in ((8,2,2,4,math.pi/2),(20,4,5,5,2*math.pi/5)):
            w=synthesize_winding(slots,poles,m,pitch)
            self.assertEqual(w['status'],'BALANCED')
            axes=[p['axis_rad'] for p in w['phase_data']]
            for i in range(1,m):self.assertAlmostEqual((axes[i]-axes[0])%(2*math.pi),i*step,places=10)
    def test_unbalanced_rejected_and_no_fake_saliency(self):
        w=synthesize_winding(10,2,3,5)
        self.assertEqual(w['status'],'UNBALANCED')
        with self.assertRaises(ValueError):build_motor(w,fundamental_b_t=.5,active_length_mm=50,airgap_radius_mm=20)
    def test_flux_geometry_emf_energy_derivative_and_power(self):
        for kind in ('rotary','linear'):
            m=self.model(kind);q=.123;speed=7.;currents=[1.,-2.,.7]
            r=evaluate(m,q,speed,currents);delta=1e-7
            a=evaluate(m,q-delta,speed,currents);b=evaluate(m,q+delta,speed,currents)
            derivative=sum(i*(v-u)/(2*delta) for i,u,v in zip(currents,a['flux_linkage_Wb'],b['flux_linkage_Wb']))
            effort=r.get('torque_Nm',r.get('force_N'))
            self.assertAlmostEqual(derivative/effort,1.,places=7)
            self.assertAlmostEqual(r['electromagnetic_power_W'],effort*speed,places=12)
        p=self.model()['phase_data'][0]
        expected=120*p['kw']*2*.5*.05*.02/2
        self.assertAlmostEqual(p['flux_linkage_peak_Wb'],expected,places=12)
    def test_mechanics_independent_constant_torque_solution(self):
        m=self.model();inertia=.01;damping=.02;peak=2;duration=.2
        lam=m['phase_data'][0]['flux_linkage_peak_Wb'];effort=1.5*2*lam*peak
        expected=effort/damping*(1-math.exp(-damping*duration/inertia))
        errors=[]
        for dt in (.04,.02,.01):
            r=simulate_motion(m,peak_current=peak,inertia_or_mass=inertia,damping=damping,duration=duration,dt=dt)
            errors.append(abs(r['samples'][-1]['speed']-expected))
        self.assertLess(errors[2],errors[1]/10);self.assertLess(errors[1],errors[0]/10)
    def test_events_and_pm_input(self):
        m=self.model('linear');v=2.;events=phase_events(m,v)
        self.assertAlmostEqual(events['electrical_period_s'],2*.03/v)
        for event in events['events']:
            if 'zero' in event['event']:
                value=evaluate(m,event['mechanical_position'],v,[0,0,0])['back_emf_V'][event['phase']]
                self.assertLess(abs(value),1e-10)
        b=pm_airgap_fundamental(remanence_t=1.2,magnet_thickness_mm=3,gap_mm=1,recoil_mu_r=1)
        self.assertAlmostEqual(b['plateau_b_t'],.9)
        with self.assertRaises(ValueError):simulate_motion(m,peak_current=1,inertia_or_mass=1,dt=1e-9)
    def test_all_phase_count_presets_and_mmf_tensor(self):
        for m in range(2,13):
            w=synthesize_winding(4*m,2,m,2*m)
            self.assertEqual(w['status'],'BALANCED')
            self.assertEqual(len(w['phase_data']),m)
            self.assertLess(w['phase_axis_tensor_error'],1e-10)
            self.assertTrue(all(p['coil_count']==4 for p in w['phase_data']))
            if m%2==0:self.assertIn('independent H-bridge',w['phase_topology'])
        with self.assertRaises(ValueError):synthesize_winding(36,4,3,8,style='distributed')
    def test_reverse_events_and_standstill(self):
        m=self.model()
        self.assertEqual(phase_events(m,0)['status'],'UNKNOWN_AT_STANDSTILL')
        for speed in (2.,-2.):
            for event in phase_events(m,speed)['events']:
                q=event['mechanical_position'];i=event['phase'];step=1e-6
                before=evaluate(m,q-speed*step,speed,[0,0,0])['back_emf_V'][i]
                after=evaluate(m,q+speed*step,speed,[0,0,0])['back_emf_V'][i]
                value=evaluate(m,q,speed,[0,0,0])['back_emf_V'][i]
                if 'negative-going' in event['event']:self.assertGreater(before,after)
                if 'positive-going' in event['event']:self.assertLess(before,after)
                if event['event']=='Positive EMF peak':self.assertGreater(value,0)
                if event['event']=='Negative EMF peak':self.assertLess(value,0)
    def test_spice_mechanics_requests_bounded_native_transient(self):
        response=dict(engine='KiCad ngspice shared library',version='test',path='library',log=[],vectors={'time':{'real':[.1]},'v(position)':{'real':[.2]},'v(speed)':{'real':[2.]}})
        with patch('wayricad_runtime.spice_backend.simulate',return_value=response) as simulator:
            result=simulate_motion_spice(self.model(),peak_current=2,inertia_or_mass=.01,damping=.02,duration=.1,dt=.001)
        self.assertEqual(simulator.call_args.kwargs['analysis'],'tran')
        self.assertIn('Gposition 0 position speed 0 1',simulator.call_args.args[0])
        self.assertEqual(result['samples'][0]['position'],.2)
        self.assertAlmostEqual(result['samples'][0]['electromagnetic_power_W'],result['samples'][0]['mechanical_power_W'])
if __name__=='__main__':unittest.main()
