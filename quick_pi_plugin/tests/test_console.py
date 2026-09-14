import copy
import math
import shlex
import unittest

from quick_pi_plugin.console import parse_command, suggestions


INVENTORY = {'nets': ['Power input', '/VCORE', 'GND'], 'terminals': [
    {'id': 'source', 'label': 'C1.1', 'net': 'Power input'},
    {'id': 'same', 'label': 'C2.1', 'net': 'Power input'},
    {'id': 'rin', 'label': 'R1.1', 'net': 'Power input'},
    {'id': 'rout', 'label': 'R1.2', 'net': '/VCORE'},
    {'id': 'lin', 'label': 'L1.1', 'net': '/VCORE'},
    {'id': 'lout', 'label': 'L1.2', 'net': 'GND'},
    {'id': 'sink', 'label': 'U8.2', 'net': '/VCORE'},
    {'id': 'last', 'label': 'Q2.3', 'net': 'GND'},
]}


class ConsoleTest(unittest.TestCase):
    def parse(self, text):
        return parse_command(text, INVENTORY)

    def model(self, value):
        return self.parse('run pi C1.1 R1.1 ' + value + ' R1.2 U8.2')['series'][0]

    def test_explicit_and_inferred_net(self):
        expected = {'action': 'solve', 'net': 'Power input',
                    'source_terminal': 'source', 'sink_terminal': 'same', 'series': []}
        self.assertEqual(self.parse('run pi "Power input" C1.1 C2.1'), expected)
        self.assertEqual(self.parse('run pi source same'), expected)

    def test_resistor_and_explicit_series_rl(self):
        self.assertEqual(self.model('5m'), {'id': 'R1', 'from_pad': 'rin',
                         'to_pad': 'rout', 'resistance_ohm': .005, 'inductance_h': 0.})
        model = self.model('5mH+30m')
        self.assertEqual(model['inductance_h'], .005)
        self.assertEqual(model['resistance_ohm'], .03)
        self.assertEqual(self.model('30mΩ+5mH'), model)

    def test_si_prefixes_units_and_scientific_notation(self):
        for value, expected in [('1m', 1e-3), ('1M', 1e6), ('1Megohm', 1e6),
                                ('1k', 1e3), ('1KΩ', 1e3), ('1u', 1e-6),
                                ('1µ', 1e-6), ('1μ', 1e-6), ('1n', 1e-9),
                                ('1p', 1e-12), ('1f', 1e-15), ('1G', 1e9),
                                ('1T', 1e12), ('1.5e+2mohms', .15), ('2e-3', .002)]:
            with self.subTest(value=value):
                self.assertTrue(math.isclose(self.model(value)['resistance_ohm'], expected, rel_tol=1e-12))
        self.assertEqual(self.model('1e-3H+2e+1m')['inductance_h'], .001)

    def test_multiple_branches_and_shortcut_orientation(self):
        explicit = self.parse('run pi C1.1 R1.1 5m+10nH R1.2 L1.1 5mH+30m L1.2 Q2.3')
        short = self.parse('run pi C1.1 R1:5m:10nH L1:30m:5mH Q2.3')
        self.assertEqual(explicit, short)
        reversed_branch = self.parse('run pi U8.2 R1:5m C1.1')['series'][0]
        self.assertEqual((reversed_branch['from_pad'], reversed_branch['to_pad']), ('rout', 'rin'))

    def test_bad_values_are_rejected_without_execution(self):
        for text in ['nan', 'inf', '1e999', '-1m', '0', '5m+30m', '1h',
                     '1mH+', '1mH+2mH', '1m;print(1)', '__import__("os")', '1m+-2H']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.model(text)

    def test_actual_net_chain_and_component_validation(self):
        invalid = ['run pi C1.1 U8.2', 'run pi GND C1.1 C2.1',
                   'run pi C1.1 R1.1 5m L1.2 Q2.3',
                   'run pi C1.1 R1.2 5m R1.1 C2.1',
                   'run pi C1.1 R1.1 5m R1.2 Q2.3',
                   'run pi C1.1 C1.1', 'run pi C1.1 R1.1 5m R1.1 C2.1',
                   'run pi C1.1 R1.1 5m R1.2', 'run pi Missing C2.1',
                   'run pi C1.1 R1:5m:10n U8.2', 'run pi C1.1 C1:5m U8.2',
                   'run pi "Power input C1.1 C2.1', 'rm -rf .']
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_ambiguous_or_unassigned_terminal_and_shortcut(self):
        inventory = copy.deepcopy(INVENTORY)
        inventory['terminals'].append({'id': 'duplicate', 'label': 'C1.1', 'net': 'GND'})
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            parse_command('run pi C1.1 C2.1', inventory)
        inventory = copy.deepcopy(INVENTORY)
        inventory['terminals'][0]['net'] = ''
        with self.assertRaisesRegex(ValueError, 'no assigned net'):
            parse_command('run pi C1.1 C2.1', inventory)
        inventory = copy.deepcopy(INVENTORY)
        inventory['terminals'][3]['net'] = 'Power input'
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            parse_command('run pi C1.1 R1:5m C2.1', inventory)

    def test_console_output_and_full_line_completion(self):
        self.assertIn('run pi', self.parse('help')['console_output'])
        self.assertIn('Power input', self.parse('nets')['console_output'])
        self.assertIn('R1.2', self.parse('pads /VCORE')['console_output'])
        self.assertNotIn('R1.1', self.parse('pads /VCORE')['console_output'])
        self.assertEqual(suggestions('ru', INVENTORY), ['run pi'])
        self.assertEqual(suggestions('run p', INVENTORY), ['run pi'])
        for text in ['run pi Pow', 'run pi "Power ', "run pi 'Power "]:
            self.assertEqual([shlex.split(x) for x in suggestions(text, INVENTORY)],
                             [['run', 'pi', 'Power input']])
        self.assertEqual(suggestions('run pi C1.1 R1.', INVENTORY),
                         ['run pi C1.1 R1.1', 'run pi C1.1 R1.2'])


if __name__ == '__main__':
    unittest.main()
