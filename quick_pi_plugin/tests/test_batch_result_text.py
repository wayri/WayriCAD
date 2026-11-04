"""Batch Results retain numerical evidence, complete paths and failure status."""
from copy import deepcopy

from quick_pi_plugin.batch_result_text import case_result_text
from quick_pi_plugin.tests.test_series_power_tree import solved_bundle


def test_series_results_show_numerical_summary_both_banks_and_every_current_pin():
    electrical=solved_bundle()
    electrical['result'].update(voltage_drop_V=.3166666666666666,total_power_W=.6333333333333332)
    row=dict(name='Full path',status='COMPLETED',electrical=electrical);before=deepcopy(row)
    text=case_result_text(row)
    for value in ('Full path · COMPLETED','Source voltage: 3.3 V','Load current: 2 A',
            'Load voltage: 2.98333 V','Path drop: 0.316667 V','Total loss: 0.633333 W',
            'VIN [copper]','MID [copper]','OUT [copper]',
            'Q1 || Q2 [parallel_stage]','Q3 || Q4 [parallel_stage]',
            'Q1: Vin','Q2: Vin','I 1.33333 A','I 0.666667 A'):
        assert value in text
    for reference,numbers in [('J1',(1,2)),('J2',(1,2)),
            ('Q1',(1,2,3,4)),('Q2',(1,2,3,4)),('Q3',(1,2,3,4)),('Q4',(1,2,3,4))]:
        for number in numbers:assert reference+'.'+str(number) in text
    for reference in ('Q1','Q2','Q3','Q4'):assert reference+'.5' not in text
    assert row==before


def test_nonseries_multiload_results_keep_total_and_individual_load_metrics():
    row=dict(name='Rail',status='COMPLETED',electrical=dict(result=dict(source_voltage_V=5.,
        total_sink_current_A=3.,total_power_W=.12,sinks=[
            dict(label='U1.1',current_A=1.,voltage_V=4.95,voltage_drop_V=.05),
            dict(label='U2.1',current_A=2.,voltage_V=4.96,voltage_drop_V=.04)])))
    text=case_result_text(row)
    assert 'Rail · COMPLETED' in text and 'Load current: 3 A' in text
    assert 'Load voltage: Unavailable' in text and 'Path drop: Unavailable' in text
    assert 'Load U1.1 · Current: 1 A · Voltage: 4.95 V · Drop: 0.05 V' in text
    assert 'Load U2.1 · Current: 2 A · Voltage: 4.96 V · Drop: 0.04 V' in text


def test_missing_nonfinite_or_boolean_metrics_are_not_replaced_with_inputs_or_zero():
    row=dict(name='Incomplete evidence',status='INCOMPLETE',electrical=dict(
        request=dict(source_voltage=12.,sink_current=4.),result=dict(
            source_voltage_V=None,sink_current_A=True,sink_voltage_V=float('nan'),
            voltage_drop_V=float('inf'),total_power_W='0.1')))
    text=case_result_text(row)
    assert text.count('Unavailable')==5
    assert '12 V' not in text and '4 A' not in text and '0 W' not in text


def test_failures_remain_visible_and_return_loop_uses_its_own_delivered_voltage():
    assert case_result_text(dict(name='Broken',status='FAILED',error='No connected copper'))==(
        'Broken · FAILED\nNo connected copper')
    row=dict(name='Returned rail',status='INFEASIBLE',electrical=dict(result=dict(
        source_voltage_V=3.3,sink_current_A=2.,sink_voltage_V=3.2,voltage_drop_V=.1,total_power_W=.2)),
        loop=dict(delivered_load_voltage_V=3.15,total_drop_V=.15,total_loss_W=.3))
    text=case_result_text(row)
    assert 'Returned rail · INFEASIBLE' in text and 'Load voltage: 3.2 V' in text
    assert 'Delivered load voltage: 3.15 V' in text
    assert 'Total loop drop: 0.15 V' in text and 'Total loop loss: 0.3 W' in text
