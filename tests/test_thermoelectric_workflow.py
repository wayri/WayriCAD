import copy
import json
import os
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch
from wayricad_runtime import thermoelectric_study as intake
from wayricad_runtime.thermoelectric_study import run_study,parse_study,parse_report,load_report,sample_temperature,validate_report
from wayricad_runtime.thermoelectric_report import render_report


def study():
    return dict(schema_version=1,grid=dict(edges_mm=dict(x=[0,1,2,3],y=[0,1],z=[0,1])),
        materials={'metal':dict(thermal_conductivity_w_mk=10,resistivity_ohm_m=.001)},
        material_ids=['metal']*3,fixed_voltage_v={'0':.1,'2':0},fixed_temperature_c={'0':20,'2':20},
        settings=dict(temperature_bounds_c=[-50,200]))


class SharedStudyTests(unittest.TestCase):
    def test_heater_pcm_retains_documented_3d_examples(self):
        from pathlib import Path
        from build_pcm import plugin_files
        base=Path(__file__).resolve().parents[1]/'heater_designer_plugin'
        names={path.relative_to(base).as_posix() for path in plugin_files(base)}
        for name in ('3d-copper-flex-study.json','3d-inconel-rigid-flex-study.json','3d-custom-thick-film-study.json'):
            self.assertIn('examples/'+name,names)

    def test_offline_interactive_report_contains_real_units_and_source(self):
        report=run_study(study());html=render_report(report)
        self.assertIn('data:text/javascript;base64,',html)
        self.assertIn('Joule density (W/m3)',html);self.assertIn('thermal3DProbeCell',html)
        self.assertNotIn('__STUDY_JSON__',html)
        self.assertIn(report['request_sha256'],html)

    def test_tampered_input_and_result_are_rejected(self):
        report=run_study(study())
        for key in ('request','result'):
            changed=copy.deepcopy(report)
            changed[key]['tampered']=True
            with self.assertRaisesRegex(ValueError,'changed'):validate_report(changed)

    def test_public_probe_rejects_tampered_request_and_temperature(self):
        report=run_study(study())
        for key in ('request','result'):
            changed=copy.deepcopy(report)
            if key=='request':changed[key]['fixed_voltage_v']['0']=2.
            else:changed[key]['temperatures_c'][0]=999.
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'changed'):
                sample_temperature(changed,.5,.5,.5)

    def test_probe_has_no_outside_or_void_nearest_fill(self):
        report=run_study(study())
        self.assertEqual(sample_temperature(report,.5,.5,.5)['cell_index'],0)
        with self.assertRaisesRegex(ValueError,'outside'):sample_temperature(report,-1,.5,.5)
        with self.assertRaisesRegex(ValueError,'identity'):sample_temperature(report,.5,.5,.5,request_sha256='wrong')

    def test_duplicate_nonfinite_and_deep_json_rejected(self):
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e999}', '{"x":'+'['*40+'0'+']'*40+'}'):
            with self.assertRaises(ValueError):parse_study(text)

    def test_aggregate_budget_counts_keys_containers_and_leaves(self):
        with patch.object(intake,'MAX_REQUEST_NODES',8):
            self.assertEqual(parse_study('{"values":[0,0,0,0,0]}')['values'],[0]*5)
            for text in ('{"values":[0,0,0,0,0,0]}','{"a":{},"b":{},"c":{},"d":{}}'):
                with self.assertRaisesRegex(ValueError,'aggregate node budget'):parse_study(text)

    def test_wide_tree_walk_does_not_queue_every_leaf(self):
        data={'values':[0]*200000}
        tracemalloc.start()
        try:
            intake._check_tree(data,intake.MAX_REQUEST_NODES)
            peak=tracemalloc.get_traced_memory()[1]
        finally:tracemalloc.stop()
        self.assertLess(peak,256*1024)

    def test_report_intake_has_separate_byte_and_node_budgets(self):
        report=run_study(study());text=json.dumps(report)
        with patch.object(intake,'MAX_BYTES',100):
            with self.assertRaisesRegex(ValueError,'bounded UTF-8'):parse_study(text)
            self.assertEqual(parse_report(text),report)
        with patch.object(intake,'MAX_REPORT_BYTES',100):
            with self.assertRaisesRegex(ValueError,'bounded UTF-8'):parse_report(text)
        with patch.object(intake,'MAX_REPORT_NODES',10):
            with self.assertRaisesRegex(ValueError,'aggregate node budget'):parse_report(text)
        with self.assertRaisesRegex(ValueError,'converged'):parse_report(json.dumps(study()))
        report['result']['temperatures_c'][0]=999
        with self.assertRaisesRegex(ValueError,'changed'):parse_report(json.dumps(report))

    def test_bounded_report_file_intake(self):
        report=run_study(study())
        with tempfile.TemporaryDirectory(dir=os.environ.get('TEMP')) as folder:
            path=Path(folder)/'report.json'
            path.write_text(json.dumps(report),encoding='utf-8-sig')
            self.assertEqual(load_report(path),report)
            with patch.object(intake,'MAX_REPORT_BYTES',100):
                with self.assertRaisesRegex(ValueError,'exceeds'):load_report(path)
            path.write_bytes(b'\xff')
            with self.assertRaisesRegex(ValueError,'UTF-8'):load_report(path)

    def test_fifty_thousand_cell_export_roundtrip(self):
        request=dict(schema_version=1,
            grid=dict(edges_mm=dict(x=list(range(51)),y=list(range(51)),z=list(range(21)))),
            materials={'metal':dict(thermal_conductivity_w_mk=10,resistivity_ohm_m=.001)},
            material_ids=['metal']*50000,
            fixed_voltage_v={str(i):0. for i in range(50000)},
            fixed_temperature_c={str(i):20. for i in range(50000)},
            settings=dict(max_cells=50000))
        report=run_study(request)
        text=json.dumps(report,indent=2,allow_nan=False)
        self.assertGreater(len(text.encode('utf-8')),intake.MAX_BYTES)
        restored=parse_report(text)
        self.assertEqual(len(restored['result']['temperatures_c']),50000)
        self.assertEqual(restored['result_sha256'],report['result_sha256'])
        self.assertEqual(sample_temperature(restored,.5,.5,.5)['temperature_c'],20.)

    def test_report_json_text_cannot_inject_script(self):
        request=study();request['provenance']={'name':'</script><script>alert(1)</script>'}
        html=render_report(run_study(request))
        self.assertNotIn('</script><script>alert(1)',html)
