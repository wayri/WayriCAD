"""Exact-sample review and recoverable publication of lumped studies."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from unittest.mock import patch

from wayricad_runtime.transient_review import review_rows, review_html
from wayricad_runtime.transient_study import execute_study, write_study_report


ROOT = Path(__file__).resolve().parents[1]


def thermal_bundle():
    from quick_therm_plugin.transient import solve_transient
    study = json.loads((ROOT/'quick_therm_plugin/studies/transient-power-step.json').read_text())
    return execute_study({'study': study}, solve_transient)


class TransientReviewTests(unittest.TestCase):
    def test_capacitor_branch_units_and_trace_selection_are_explicit(self):
        from wayricad_runtime.transient_review import capacitor_rows
        branch=dict(id='C1',capacitance_F=1e-7,esr_ohm=.01,esl_H=1e-9,
                    current_A=[-.2,.1],capacitor_voltage_V=[3.2,3.3],
                    esr_loss_W=[.0004,.0001],stored_energy_J=[1e-6,2e-6])
        result=dict(times_s=[0.,1.],loads=[dict(id='U1',voltage_V=[3.3,3.1],
                    requested_current_A=[0.,1.],limits={},shunt_capacitors=[branch])],
                    checks=dict(time_refinement=dict(per_shunt_capacitor=[dict(load_id='U1',id='C1',max_voltage_difference_V=.01)])))
        row=capacitor_rows(result)[0]
        self.assertEqual(row['peak_current_A'],.2)
        self.assertEqual(row['half_step_difference_V'],.01)
        text=review_html({'transient':result})
        self.assertIn('<td>0.1</td><td>10</td><td>1</td>',text)
        self.assertIn('U1 / C1 · internal C voltage',text)
        self.assertIn('Capacitor current · A',text)
        self.assertIn('id="transient-caps"',text)
        self.assertIn('value="1"',text)

    def test_unspecified_limits_are_not_a_pass_and_statistics_are_exact(self):
        result = thermal_bundle()['transient']; original = copy.deepcopy(result)
        result['components'][0]['limit_c'] = None
        rows = review_rows(result)
        self.assertEqual(rows[0]['status'], 'NOT EVALUATED')
        self.assertEqual(rows[0]['maximum'], max(result['components'][0]['temperature_c']))
        self.assertEqual(rows[0]['final'], result['components'][0]['temperature_c'][-1])
        result['components'][0]['limit_c'] = original['components'][0]['limit_c']
        self.assertEqual(result, original)

    def test_pi_constraint_failures_and_duplicate_event_samples_are_retained(self):
        result = dict(times_s=[0, 1, 1], sample_phase=['sample', 'step_before', 'step_after'],
                      loads=[dict(id='J1.1', voltage_V=[3.3, 3.3, 2.8], requested_current_A=[0, 0, 1],
                                  limits={'min_voltage_V': 3}, violations=[{'kind':'minimum_voltage'}])])
        self.assertEqual(review_rows(result)[0]['status'], 'FAIL')
        text = review_html({'transient': result})
        self.assertIn('step_before', text)
        self.assertIn('step_after', text)
        self.assertIn('"times":[0,1,1]', text)
        self.assertIn('Requested current', text)

    def test_untrusted_identifiers_remain_text_and_one_trace_is_drawn(self):
        bundle = thermal_bundle(); attack = '</script><script>alert(1)</script>'
        bundle['transient']['components'][0]['reference'] = attack
        text = review_html(bundle)
        self.assertNotIn(attack, text)
        self.assertIn('\\u003c/script>', text)
        self.assertIn('data.rows[selected]', text)
        self.assertIn('li.textContent=description()', text)
        self.assertIn('while(low<high)', text)

    def test_input_file_is_bound_before_during_and_after_solve(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'input.json'; source.write_text('{"value":1}')
            request = dict(study={'value':1}, study_input_path=str(source),
                           study_file_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            source.write_text('{"value":2}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                execute_study(request, lambda _: self.fail('ran'))
            source.write_text('{"value":1}')
            def mutate(_):
                source.write_text('{"value":2}')
                return {}
            with self.assertRaisesRegex(ValueError, 'during'):
                execute_study(request, mutate)
            source.write_text('{"value":1}')
            revised = execute_study({**request, 'study':{'value':3}}, lambda model:dict(model))
            self.assertEqual(revised['study'], {'value':3})
            self.assertEqual(revised['study_file_sha256'], request['study_file_sha256'])
            bundle = thermal_bundle()
            source.write_text(json.dumps(bundle['study']))
            from quick_therm_plugin.transient import solve_transient
            bundle = execute_study(dict(study=bundle['study'], study_input_path=str(source)), solve_transient)
            source.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                write_study_report(Path(directory)/'report.html', bundle)
            self.assertFalse((Path(directory)/'report.json').exists())

    def test_report_pair_rolls_back_and_preserves_prior_evidence(self):
        import wayricad_runtime.report_ui as publication
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'report.html'; evidence = output.with_suffix('.json')
            output.write_bytes(b'previous html'); evidence.write_bytes(b'previous json')
            replace = publication.os.replace; failed = False
            def fail_once(source, target):
                nonlocal failed
                if Path(target)==output and not failed:
                    failed=True
                    raise OSError('injected HTML publication failure')
                return replace(source, target)
            with patch.object(publication.os, 'replace', side_effect=fail_once):
                with self.assertRaisesRegex(OSError, 'publication failure'):
                    write_study_report(output, thermal_bundle())
            self.assertEqual(output.read_bytes(), b'previous html')
            self.assertEqual(evidence.read_bytes(), b'previous json')
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    @unittest.skipUnless(shutil.which('node'), 'Node runtime required for report interaction logic')
    def test_report_javascript_selects_exact_samples_and_bounds_probes(self):
        from wayricad_runtime.transient_review import _SCRIPT
        harness = r'''
const {script}=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const assert=require('node:assert/strict'),vm=require('node:vm');
const data={times:[0,1,1],phases:['sample','step_before','step_after'],unit:'V',secondary:'Requested current · A',rows:[{label:'U1',values:[3.3,3.3,2.8],secondary:[0,0,1]},{label:'U2',values:[5,4,3],secondary:[1,2,3]}]};
const noop=()=>{},context=new Proxy({},{get:()=>noop,set:()=>true});
const element=()=>({value:'0',children:[],style:{},dataset:{},setAttribute:noop,append(item){this.children.push(item)},replaceChildren(){this.children=[]}});
const ids=Object.fromEntries(['transient-unit','transient-sample','transient-trace','transient-value','transient-probes','transient-pin','transient-clear'].map(id=>[id,element()]));
ids['transient-trace'].clientWidth=1024;ids['transient-trace'].getContext=()=>context;ids['transient-trace'].getBoundingClientRect=()=>({left:0,width:1024});
const rows=[element(),element()],buttons=[element(),element()];rows.forEach((r,i)=>r.dataset.unit=String(i));buttons.forEach((r,i)=>r.dataset.unit=String(i));
const document={getElementById:id=>ids[id],createElement:element,querySelectorAll:selector=>selector.includes('button')?buttons:rows};
vm.runInNewContext('const data='+JSON.stringify(data)+';'+script,{document,ResizeObserver:class{observe(){}}});
assert.match(ids['transient-value'].textContent,/U1.*sample 0/);
buttons[1].onclick();assert.equal(ids['transient-unit'].value,'1');assert.equal(rows[1].style.background,'#dff1f3');
ids['transient-sample'].value='2';ids['transient-sample'].oninput();assert.match(ids['transient-value'].textContent,/U2.*step_after.*3\.0000000 V/);
ids['transient-pin'].onclick();assert.match(ids['transient-probes'].children[0].textContent,/U2.*step_after/);
ids['transient-sample'].value='1';ids['transient-sample'].oninput();assert.match(ids['transient-value'].textContent,/step_before.*4\.0000000 V/);
for(let i=0;i<105;i++)ids['transient-pin'].onclick();assert.equal(ids['transient-probes'].children.length,100);
ids['transient-clear'].onclick();assert.equal(ids['transient-probes'].children.length,0);
ids['transient-trace'].onpointermove({clientX:55});assert.equal(ids['transient-sample'].value,'0');
console.log('Cross-selection, exact event phases, hover lookup and bounded probes passed');
'''
        result = subprocess.run([shutil.which('node'), '-e', harness],
                                input=json.dumps({'script':_SCRIPT}), text=True,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
