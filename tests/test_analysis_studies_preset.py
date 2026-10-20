"""The shared analysis job preset requires reviewed models rather than guessed nets."""
from wayricad_runtime.job_presets import PRESETS,REQUIRED_VARIABLES
from wayricad_runtime.jobs import SCHEMA,validate

def test_analysis_studies_preserve_explicit_inputs_and_three_report_pairs():
    steps=PRESETS['analysis-studies']
    assert REQUIRED_VARIABLES['analysis-studies']==('pi_study','si_study','thermal_config')
    assert '--batch' in steps[0]['argv'] and '${pi_study}' in steps[0]['argv']
    assert 'study' in steps[1]['argv'] and '${si_study}' in steps[1]['argv']
    assert '--require-limits-pass' in steps[2]['argv']
    assert all(len(step['outputs'])==2 for step in steps)
    validate({'schema':SCHEMA,'variables':{key:key+'.json' for key in REQUIRED_VARIABLES['analysis-studies']},'steps':steps})
