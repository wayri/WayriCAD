import unittest
from unittest.mock import patch
from signal_integrity_advisor_plugin import thermal_feedback
from wayricad_runtime.thermoelectric_study import run_study
from signal_integrity_advisor_plugin.thermal_feedback import mapping_template,apply_temperature


class ThermalFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.thermal=run_study(dict(schema_version=1,grid=dict(edges_mm=dict(x=[0,1,2],y=[0,1],z=[0,1])),
            materials={'solid':dict(thermal_conductivity_w_mk=10)},material_ids=['solid']*2,
            fixed_voltage_v={},fixed_temperature_c={'0':20,'1':100}))
        self.path={'path':{'segments':[{'resistance_ohm':1},{'resistance_ohm':2}]}}
        self.mapping=mapping_template(self.path,self.thermal)
        self.mapping['reviewed']=True
        self.mapping['sections'][0]['samples_mm']=[[.5,.5,.5]]
        self.mapping['sections'][1]['samples_mm']=[[1.5,.5,.5]]

    def test_temperature_changes_dc_resistance_and_declared_joule_loss(self):
        result=apply_temperature(self.path,self.thermal,self.mapping,2)
        self.assertAlmostEqual(result['resistance_dc_ohm'],1+2*(1+.00393*80))
        self.assertAlmostEqual(result['joule_power_w'],4*result['resistance_dc_ohm'])

    def test_stale_path_or_unreviewed_mapping_is_rejected(self):
        self.path['changed']=True
        with self.assertRaisesRegex(ValueError,'identity'):apply_temperature(self.path,self.thermal,self.mapping)
        self.mapping['reviewed']=False
        with self.assertRaisesRegex(ValueError,'review'):apply_temperature(self.path,self.thermal,self.mapping)

    def test_outside_sample_not_assigned_nearest_temperature(self):
        self.mapping['sections'][0]['samples_mm']=[[-1,.5,.5]]
        with self.assertRaisesRegex(ValueError,'outside'):apply_temperature(self.path,self.thermal,self.mapping)

    def test_batch_validates_report_once_not_per_sample(self):
        for entry in self.mapping['sections']:entry['samples_mm']*=20
        with patch.object(thermal_feedback,'validate_report',wraps=thermal_feedback.validate_report) as validate:
            result=apply_temperature(self.path,self.thermal,self.mapping)
        validate.assert_called_once_with(self.thermal)
        self.assertEqual([row['sample_count'] for row in result['sections']],[20,20])

    def test_tampered_thermal_result_rejected_before_sampling(self):
        self.thermal['result']['temperatures_c'][0]=99.
        with patch.object(thermal_feedback,'_sample_temperature_validated') as sample:
            with self.assertRaisesRegex(ValueError,'changed'):
                apply_temperature(self.path,self.thermal,self.mapping)
        sample.assert_not_called()
