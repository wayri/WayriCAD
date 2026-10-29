import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_allclose

from quick_emerge_plugin.network import SampledNetwork
from quick_emerge_plugin.network_extensions import (serialize_network,deserialize_network,embed_components,
                                                    rational_fit,touchstone_text,export_touchstone,apply_operation)
from quick_emerge_plugin.network_worker import run_request
from quick_emerge_plugin.tests.test_reporting import fixture


def component(element,value,connection='shunt',ports=None):
    return {'element':element,'connection':connection,'value_si':value,'unit':{'R':'ohm','L':'H','C':'F'}[element],'ports':[0] if ports is None else ports}


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[2]/'.validation/quick-emerge-v2/networkextensions';scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_rlc_one_port_matches_independent_load_equations(self):
        f=np.array([1e8,5e8,1e9]);omega=2*np.pi*f
        original=SampledNetwork(f,np.zeros((3,1,1)))
        for element,value,z in [('R',50,np.full(3,50)),('L',2e-9,1j*omega*2e-9),('C',.5e-12,1/(1j*omega*.5e-12))]:
            for connection in ('shunt','series'):
                with self.subTest(element=element,connection=connection):
                    result=embed_components(original,[component(element,value,connection)])
                    load=1/(1/50+1/z) if connection=='shunt' else 50+z
                    expected=(load-50)/(load+50)
                    assert_allclose(result.s[:,0,0],expected,atol=3e-15)
                    self.assertEqual(result.provenance['transformations'][0]['unit'],{'R':'ohm','L':'H','C':'F'}[element])
        assert_allclose(original.s,0)

    def test_two_node_shunt_branch_and_element_order(self):
        original=SampledNetwork([1e9],np.zeros((1,2,2)))
        result=embed_components(original,[component('R',50,ports=[0,1])])
        assert_allclose(result.s,[[[-.25,.25],[.25,-.25]]],atol=1e-15)
        base=SampledNetwork([1e9],[[[0]]])
        a=embed_components(base,[component('R',50,'series'),component('R',50)])
        b=embed_components(base,[component('R',50),component('R',50,'series')])
        assert_allclose(a.s,-.2,atol=1e-15);assert_allclose(b.s,.2,atol=1e-15)

    def test_component_rejections_and_representation_limits(self):
        original=SampledNetwork([1e9],np.zeros((1,2,2)))
        invalid=[component('R',True),component('L',-1),component('C',float('nan')),component('R',0),
                 component('R',50,'series',[0,1]),component('R',50,ports=[0,0]),component('R',50,ports=[3]),
                 {**component('C',1e-12),'unit':'pF'},{**component('R',50),'expression':'x()'}]
        for item in invalid:
            with self.subTest(item=item),self.assertRaises(ValueError):embed_components(original,[item])
        with self.assertRaises(ValueError):embed_components(original,[])
        thru=SampledNetwork([1e9],[[[0,1],[1,0]]])
        with self.assertRaisesRegex(ValueError,'singular'):embed_components(thru,[component('R',50,'series')])

    def test_serialization_preserves_per_port_references_port_order_and_history(self):
        n=SampledNetwork([1e9],[[[.1,.2],[.3,.4]]],[25,100],['left','right'],{'transforms':['reviewed']})
        n.s.setflags(write=True)
        n.s[0,0,0]=complex(-0.0,-0.0)
        n.s.setflags(write=False)
        payload=serialize_network(n);back=deserialize_network(payload)
        self.assertTrue(np.signbit(back.s.real[0,0,0]))
        self.assertTrue(np.signbit(back.s.imag[0,0,0]))
        assert_allclose(back.s,n.s);assert_allclose(back.z0_ohm,[25,100])
        self.assertEqual(back.port_names,('left','right'));self.assertEqual(back.provenance,n.provenance)
        payload['s_parameters']['S12'][0][0]=99
        with self.assertRaisesRegex(ValueError,'hash'):deserialize_network(payload)

    def test_touchstone_nonreciprocal_two_and_three_port_independent_order(self):
        two=SampledNetwork([1e9],[[[11+1j,12+2j],[21+3j,22+4j]]],75)
        text=touchstone_text(two)
        self.assertIn('# Hz S RI R 75',text)
        data=[line for line in text.splitlines() if not line.startswith(('!','#'))]
        self.assertEqual(list(map(float,data[0].split())),[1e9,11,1,21,3,12,2,22,4])
        three=SampledNetwork([2e9],[np.array([[11,12,13],[21,22,23],[31,32,33]],complex)])
        lines=[line for line in touchstone_text(three).splitlines() if not line.startswith(('!','#'))]
        self.assertEqual(list(map(float,lines[0].split())),[2e9,11,0,12,0,13,0])
        self.assertEqual(list(map(float,lines[1].split())),[21,0,22,0,23,0])
        self.assertEqual(list(map(float,lines[2].split())),[31,0,32,0,33,0])
        unequal=SampledNetwork([1e9],np.zeros((1,2,2)),[25,100])
        with self.assertRaises(ValueError):touchstone_text(unequal)
        self.assertIn('# Hz S RI R 50',touchstone_text(unequal,reference_ohm=50))

    def test_touchstone_companion_protects_sources(self):
        n=SampledNetwork([1e9],[[[0]]])
        paths=export_touchstone(self.root/'derived.s1p',n)
        evidence=json.loads(Path(paths['json']).read_text(encoding='utf-8'))
        self.assertEqual(deserialize_network(evidence).digest(),n.digest())
        with self.assertRaisesRegex(ValueError,'overwrite'):
            export_touchstone(self.root/'derived.s1p',n,source_paths=[self.root/'derived.s1p'])

    def _request(self,operation):
        board=self.root/'source.kicad_pcb';board.write_text('(kicad_pcb)')
        result=fixture(board)
        source=self.root/'result.json';source.write_text(json.dumps(result),encoding='utf-8')
        path=self.root/'request.json';request={'schema':1,'source_result_path':str(source),'source_result_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'operation':operation,'output_path':str(self.root/'derived.json')}
        path.write_text(json.dumps(request),encoding='utf-8')
        return path,source,result

    def test_worker_preserves_solved_result_and_rejects_stale_board_and_file(self):
        path,source,result=self._request({'kind':'components','components':[component('C',1e-12)]})
        before=source.read_bytes();payload=run_request(path)
        self.assertEqual(source.read_bytes(),before)
        self.assertNotIn('field',payload)
        self.assertEqual(payload['kind'],'derived-network')
        self.assertEqual(payload['source_result']['sha256'],hashlib.sha256(before).hexdigest())
        self.assertEqual(payload['derived_network']['port_names'],['P1','P2'])
        Path(result['source']['path']).write_text('(changed board)')
        with self.assertRaisesRegex(ValueError,'stale'):run_request(path)
        source.write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):run_request(path)

    def test_actual_isolated_cli_and_no_source_overwrite(self):
        path,source,_=self._request({'kind':'renormalize','reference_ohm':75})
        worker=Path(__file__).resolve().parents[1]/'network_worker.py'
        process=subprocess.run([sys.executable,'-I',str(worker),str(path)],stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertIn('completed',process.stdout)
        payload=json.loads((self.root/'derived.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['derived_network']['reference_impedance_ohm'],[75,75])
        request=json.loads(path.read_text(encoding='utf-8'));request['output_path']=str(source);path.write_text(json.dumps(request),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'overwrite'):run_request(path)

    def test_fit_rejects_missing_samples_extrapolation_numeric_bools(self):
        n=SampledNetwork(np.arange(1,8),np.zeros((7,1,1)))
        for f,kwargs in [([0,3],{}),([1,8],{}),([1,1],{}),([1,7],{'tolerance':True}),([1,7],{'poles':True}),([1,7],{'method':'expression'})]:
            with self.subTest(f=f,kwargs=kwargs),self.assertRaises(ValueError):rational_fit(n,f,**kwargs)
        with self.assertRaises(ValueError):rational_fit(SampledNetwork([1,2],[[[0]],[[0]]]),[1,2])
        with self.assertRaises(ValueError):apply_operation(n,{'kind':'fit','points':True})
        with self.assertRaises(ValueError):apply_operation(n,{'kind':'eval','code':'print(1)'})

    @unittest.skipUnless(importlib.util.find_spec('emerge'),'Actual EMerge 3 solver runtime required')
    def test_real_upstream_aaa_delay_matches_independent_dense_solution(self):
        f=np.linspace(1e8,1e9,17);tau=1e-10
        s=np.zeros((17,2,2),complex);s[:,0,1]=s[:,1,0]=np.exp(-2j*np.pi*f*tau)
        dense=np.linspace(f[0],f[-1],101)
        result=rational_fit(SampledNetwork(f,s),dense,method='aaa',tolerance=1e-7)
        fitted=deserialize_network(result['derived_network'])
        assert_allclose(fitted.s[:,1,0],np.exp(-2j*np.pi*dense*tau),atol=2e-8)
        self.assertLess(result['fit']['sample_max_abs_error'],1e-7)
        self.assertLess(result['fit']['holdout_max_abs_error'],1e-7)
        self.assertTrue(result['fit']['tolerance_met'])
        self.assertIn('public_api',result['fit'])

    @unittest.skipUnless(importlib.util.find_spec('emerge'),'Actual EMerge 3 solver runtime required')
    def test_real_upstream_aaa_rlc_and_vector_fit_residual(self):
        f=np.linspace(1e7,1e9,33);omega=2*np.pi*f
        z=50+1j*omega*1e-8+1/(1j*omega*1e-11)
        s=((z-50)/(z+50))[:,None,None]
        dense=np.linspace(f[0],f[-1],101);w=2*np.pi*dense
        zd=50+1j*w*1e-8+1/(1j*w*1e-11);expected=(zd-50)/(zd+50)
        aaa=rational_fit(SampledNetwork(f,s),dense,method='aaa',tolerance=1e-7)
        assert_allclose(deserialize_network(aaa['derived_network']).s[:,0,0],expected,atol=1e-7)
        vf=rational_fit(SampledNetwork(f,s),dense,method='vf',tolerance=1e-5,poles=3)
        self.assertTrue(np.isfinite(deserialize_network(vf['derived_network']).s).all())
        self.assertLess(vf['fit']['sample_max_abs_error'],1e-3)


if __name__=='__main__':unittest.main()
