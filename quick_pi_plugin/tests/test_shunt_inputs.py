"""Explicit branch units and conservative saved-pad candidate discovery."""
import copy
import unittest

from quick_pi_plugin.shunt_caps import capacitance_value, candidates, bank_from_rows, bank_rows
from quick_pi_plugin.transient_inputs import engineering_from_study, engineering_to_study


def terminals():
    return [dict(id='p'+str(i),footprint_uuid='owner1',footprint_pad_count=2,
                 reference='C1',component_value='100nF 50V X7R',net=net)
            for i,net in enumerate(('VCC','GND'))]


class ShuntInputTests(unittest.TestCase):
    def test_units_do_not_decode_ambiguous_codes_or_wrong_dimensions(self):
        for text,expected in [('100nF',100e-9),('4n7',4.7e-9),('2u2',2.2e-6),('0.1 µF',1e-7),('1e-3F',1e-3)]:
            self.assertAlmostEqual(capacitance_value(text),expected)
        self.assertAlmostEqual(capacitance_value('.1',bare_scale=1e-6),1e-7)
        self.assertAlmostEqual(capacitance_value('CC0402_100NF_25V_X7R',allow_description=True),1e-7)
        self.assertAlmostEqual(capacitance_value('CC0603_4.7UF_25V',allow_description=True),4.7e-6)
        with self.assertRaises(ValueError):capacitance_value('100nF + 1uF',allow_description=True)
        for text in ('104','100','nanF','-1uF','0nF','1e999F','10 mΩ','100nF 50V'):
            with self.subTest(text=text),self.assertRaises(ValueError):capacitance_value(text)

    def test_only_exact_two_pad_reference_net_pairs_are_suggested(self):
        rows=terminals();before=copy.deepcopy(rows)
        found=candidates(rows,'VCC','GND')
        self.assertEqual(len(found),1);self.assertEqual(found[0]['id'],'C1@owner1')
        self.assertAlmostEqual(found[0]['capacitance_F'],100e-9)
        self.assertEqual(candidates(rows,'VCC',''),[])
        self.assertEqual(candidates(rows,'VCC','OTHER'),[])
        self.assertEqual(candidates(rows,'VCC','GND',assigned=['C1@owner1']),[])
        for key,value in [('footprint_pad_count',3),('footprint_uuid',''),('reference','R1')]:
            altered=[{**row,key:value} for row in rows]
            self.assertEqual(candidates(altered,'VCC','GND'),[])
        self.assertEqual(rows,before)
        unknown=[{**row,'component_value':'104'} for row in rows]
        self.assertIsNone(candidates(unknown,'VCC','GND')[0]['capacitance_F'])

    def test_each_branch_requires_reviewed_esr_and_esl(self):
        rows=[['C1','100nF','10','.5'],['C2','4.7','0','0']]
        bank=bank_from_rows(rows)
        self.assertAlmostEqual(bank[0]['capacitance_F'],1e-7)
        self.assertAlmostEqual(bank[0]['esr_ohm'],.01)
        self.assertAlmostEqual(bank[0]['esl_H'],.5e-9)
        self.assertAlmostEqual(bank[1]['capacitance_F'],4.7e-6)
        restored=bank_from_rows(bank_rows(bank))
        for original,row in zip(bank,restored):
            self.assertEqual(row['id'],original['id'])
            for key in ('capacitance_F','esr_ohm','esl_H'):
                self.assertAlmostEqual(row[key],original[key],delta=max(abs(original[key])*1e-12,1e-30))
        for invalid in ([['C1','1','','0']],[['C1','1','0','']],rows+[rows[0]],[['C1','1','-1','0']]):
            with self.assertRaises(ValueError):bank_from_rows(invalid)

    def test_engineering_bank_replaces_aggregate_without_mutating_rows(self):
        study=dict(source_voltage_V=3.3,source_resistance_ohm=.05,source_inductance_H=0,
                   duration_s=10e-6,step_s=1e-8,loads=[dict(id='U1',initial_current_A=0,
                   step_current_A=.1,step_time_s=2e-6,path_resistance_ohm=0,path_inductance_H=0,
                   capacitance_F=999.,esr_ohm=999.)])
        parameters,rows=engineering_from_study(study);before=copy.deepcopy(rows)
        bank=bank_from_rows([['C1','1','10','1']])
        result=engineering_to_study(parameters,rows,validate=False,banks={0:bank},rise_times={0:1e-6})
        load=result['loads'][0]
        self.assertNotIn('capacitance_F',load);self.assertNotIn('esr_ohm',load)
        self.assertEqual(load['shunt_capacitors'],bank);self.assertEqual(load['rise_time_s'],1e-6)
        self.assertEqual(rows,before);load['shunt_capacitors'][0]['esr_ohm']=123
        self.assertEqual(bank[0]['esr_ohm'],.01)


if __name__=='__main__':unittest.main()
