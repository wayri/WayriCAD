"""Read-only result reuse must never cross source/settings or mutable callers."""
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from quick_pi_plugin import service


class ResultCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'board.kicad_pcb';self.path.write_bytes(b'board')
        self.request={'action':'solve','board_path':str(self.path),'net':'VCC','edge_mm':.2}
        self.cache=patch.object(service,'_RESULT_CACHE',service._ResultCache());self.cache.start();self.addCleanup(self.cache.stop)
        self.ensure=patch('wayricad_runtime.runtime_setup.ensure_runtime',return_value='owned-python')
        self.ensure_mock=self.ensure.start();self.addCleanup(self.ensure.stop)
        self.spawn=patch.object(service.subprocess,'Popen',side_effect=self.completed)
        self.spawn_mock=self.spawn.start();self.addCleanup(self.spawn.stop)
        self.response={'result':{'potential':[1.,.9]},'geometry':{'source_sha256':'fixture'}}

    def completed(self,command,**kwargs):
        Path(command[-1]).write_text(json.dumps(self.response),encoding='utf-8')
        return types.SimpleNamespace(poll=lambda:0,returncode=0)

    def test_identical_request_reuses_worker_and_isolates_mutation(self):
        first=service.run_job(self.request);first['result']['potential'][0]=99
        second=service.run_job(dict(reversed(list(self.request.items()))))
        self.assertEqual(second['result']['potential'],[1.,.9]);second['result']['potential'].clear()
        self.assertEqual(service.run_job(self.request)['result']['potential'],[1.,.9])
        self.assertEqual(self.spawn_mock.call_count,1);self.assertEqual(self.ensure_mock.call_count,1)

    def test_content_rules_and_every_request_setting_invalidate(self):
        service.run_job(self.request)
        for path,data in [(self.path,b'changed'),(self.path.with_suffix('.kicad_pro'),b'{}'),
                          (self.path.with_suffix('.kicad_dru'),b'rules')]:
            count=self.spawn_mock.call_count;path.write_bytes(data);service.run_job(self.request)
            self.assertEqual(self.spawn_mock.call_count,count+1)
        self.path.with_suffix('.kicad_dru').unlink();service.run_job(self.request)
        count=self.spawn_mock.call_count
        for key,value in [('edge_mm',.1),('mesh_sizing','auto'),('source_voltage',3.3),
                          ('max_cells',1000),('include_display_scene',True),('display_nets',None)]:
            service.run_job({**self.request,key:value})
        self.assertEqual(self.spawn_mock.call_count,count+6)
        with patch.dict(service.os.environ,{'WAYRICAD_KICAD_PYTHON':'different-native'}):service.run_job(self.request)
        self.assertEqual(self.spawn_mock.call_count,count+7)

    def test_cache_hit_cancellation_budget_and_midread_source_change(self):
        service.run_job(self.request)
        with self.assertRaises(InterruptedError):service.run_job(self.request,cancelled=lambda:True)
        with patch.object(service.time,'monotonic',side_effect=[0.,2.]),self.assertRaises(TimeoutError):
            service.run_job(self.request,timeout=1)
        loads=json.loads
        def changed(data):
            value=loads(data);self.path.write_bytes(b'edited during cache lookup');return value
        with patch.object(service.json,'loads',side_effect=changed),self.assertRaisesRegex(ValueError,'changed'):
            service.run_job(self.request)
        self.assertEqual(self.spawn_mock.call_count,1)

    def test_changed_source_during_worker_is_not_cached(self):
        def changed(command,**kwargs):
            self.path.write_bytes(self.path.read_bytes()+b'x');return self.completed(command,**kwargs)
        self.spawn_mock.side_effect=changed
        with self.assertRaisesRegex(ValueError,'changed'):service.run_job(self.request)
        self.assertFalse(service._RESULT_CACHE.entries)

    def test_failures_and_report_requests_are_not_reused(self):
        self.response={'error':'mesh budget exceeded'}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'budget'):service.run_job(self.request)
        self.assertFalse(service._RESULT_CACHE.entries)
        self.response={'result':{}}
        for action in ('batch','converge','verify','return_path'):
            self.assertIsNone(service._request_key({**self.request,'action':action}))
        for _ in range(2):service.run_job({**self.request,'html_output':'report.html'})
        self.assertEqual(self.spawn_mock.call_count,4)

    def test_lru_has_exact_byte_and_count_bounds(self):
        cache=service._ResultCache(max_bytes=10,max_entries=2)
        cache.put('a',b'1234');cache.put('b',b'1234');self.assertEqual(cache.size,8)
        cache.get('a');cache.put('c',b'1234')
        self.assertIsNone(cache.get('b'));self.assertEqual(cache.size,8)
        cache.put('a',b'1');self.assertEqual(cache.size,5)
        cache.put('too big',b'123456');self.assertIsNone(cache.get('too big'))


class DisplayContractTests(unittest.TestCase):
    def test_display_is_opt_in_and_net_scope_matches_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'board.kicad_pcb';path.write_bytes(b'board')
            digest=hashlib.sha256(path.read_bytes()).hexdigest();board=object()
            with patch('wayricad_runtime.board_render.extract_board',return_value={'primitives':[]}) as extract:
                service._display_output({}, {},board,path,digest);extract.assert_not_called()
                examples=[({'nets':['AAA','VDD','ZZ']},{'display_nets':'default'},['VDD']),
                          ({'nets':['AAA','ZZ']},{'display_nets':'default'},['AAA']),
                          ({'nets':[]},{'display_nets':'default'},[]),
                          ({'geometry':{'net':'VCC'}},{},['VCC']),
                          ({'geometry':{'net':'A → B','nets':['A','B']}},{},['A','B']),
                          ({'geometry':{'net':'VCC'}},{'display_nets':None},None)]
                for output,settings,scope in examples:
                    result=service._display_output(output,{'include_display_scene':True,**settings},board,path,digest)
                    extract.assert_called_with(board,visible_nets=scope)
                    self.assertEqual(result['board_scene']['source_sha256'],digest)
                    self.assertEqual(result['scene_nets'],scope)
                def mutate(*args,**kwargs):path.write_bytes(b'changed');return {}
                extract.side_effect=mutate
                with self.assertRaisesRegex(ValueError,'changed during display'):
                    service._display_output({}, {'include_display_scene':True},board,path,digest)


if __name__=='__main__':unittest.main()
