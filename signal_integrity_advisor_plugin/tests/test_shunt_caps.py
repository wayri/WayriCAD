"""Reviewed endpoint shunt branch validation and engineering-unit editing."""
import copy
import unittest

from signal_integrity_advisor_plugin.shunt_caps import capacitor_branches, editor_branches, editor_rows


class ShuntCapacitorTests(unittest.TestCase):
    def test_individual_values_and_case_units_round_trip_without_mutation(self):
        mapping = {'DATA':[dict(id='C1',at='receiver',capacitance_F=1e-10,esr_ohm=.05,esl_H=1e-9),
                           dict(id='C2',at='source',capacitance_F=1e-9,esr_ohm=.1,esl_H=2e-9)]}
        original = copy.deepcopy(mapping)
        rows = editor_rows(mapping)
        self.assertEqual(rows[0], ['DATA','C1','receiver','0.1','50','1'])
        normalized=editor_branches(rows, ['DATA'])
        for actual, expected in zip(normalized['DATA'],mapping['DATA']):
            self.assertEqual((actual['id'],actual['at']),(expected['id'],expected['at']))
            for key in ('capacitance_F','esr_ohm','esl_H'):
                self.assertAlmostEqual(actual[key],expected[key],delta=abs(expected[key])*1e-14)
        self.assertEqual(mapping, original)

    def test_blank_grid_rows_are_not_implicit_capacitors(self):
        self.assertEqual(editor_branches([['DATA','','receiver','','','']], ['DATA']), {'DATA':[]})
        with self.assertRaisesRegex(ValueError,'finite number'):
            editor_branches([['DATA','C1','receiver','','','']], ['DATA'])

    def test_identifiers_are_unique_after_whitespace_normalization(self):
        base = dict(id='C1',at='source',capacitance_F=1e-9)
        with self.assertRaisesRegex(ValueError,'unique'):
            capacitor_branches([base,dict(base,id=' C1 ')])
        self.assertEqual(capacitor_branches([dict(base,id=' C1 ')])[0]['id'],'C1')

    def test_each_case_keeps_its_individual_branches(self):
        rows = [['A','C1','source','100','5','1'],['B','C1','receiver','1','20','2']]
        result = editor_branches(rows,['A','B'])
        self.assertAlmostEqual(result['A'][0]['capacitance_F'],100e-9)
        self.assertAlmostEqual(result['B'][0]['capacitance_F'],1e-9)
        with self.assertRaisesRegex(ValueError,'exported case'):editor_branches(rows,['A'])

    def test_unknown_negative_nonfinite_and_boolean_values_fail(self):
        base = dict(id='C1',at='receiver',capacitance_F=1e-9)
        for key,value in [('capacitance_F',None),('capacitance_F',True),('capacitance_F',0),
                          ('capacitance_F',float('inf')),('esr_ohm',-1),('esl_H',float('nan')),('at','midpoint')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                capacitor_branches([dict(base,**{key:value})])
        with self.assertRaisesRegex(ValueError,'fields'):capacitor_branches([dict(base,capacitance_nf=1)])

    def test_capacitor_and_export_budgets_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'64'):
            capacitor_branches([dict(id=str(i),at='receiver',capacitance_F=1e-9) for i in range(65)])
        with self.assertRaisesRegex(ValueError,'256'):editor_branches([[]]*257,['DATA'])


if __name__=='__main__':unittest.main()
