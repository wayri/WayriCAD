import json
from pathlib import Path
import tempfile
import unittest

from wayricad_runtime import assistant
from wayricad_runtime.assistant_context import CircuitInventory


NET = '/Power/PROTECTED_RAIL'
QUERY = ('run PI on PROTECTED_RAIL from J4 to U51 and U52 and U41 with each of '
         'these consuming 4A of current and the input voltage is 50V')
REPLY = 'J4.2 to U41 pins 1,2,3 and 6 and same pins for U51 and U52'


def inventory():
    pads = {'J4.1': {NET}, 'J4.2': {NET}, 'J4.3': {'GND'}}
    for ref in ('U51', 'U52', 'U41'):
        for pin in (1, 2, 3, 6):
            pads[f'{ref}.{pin}'] = {NET}
        pads[f'{ref}.4'] = {'GND'}
    return CircuitInventory((NET, 'GND'), {'J4': 'Supply connector'}, pads)


class GroupedPITests(unittest.TestCase):
    def test_connector_groups_are_suggested_then_explicitly_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            board = Path(temporary) / 'board.kicad_pcb'
            board.write_text('(kicad_pcb)')
            context = {'board': str(board)}
            first = assistant.propose(QUERY, context, inventory=inventory())
            self.assertEqual(first['status'], 'needs_input')
            self.assertEqual(first['steps'][0]['action'], 'quick-pi.grouped')
            params = first['steps'][0]['params']
            self.assertEqual((params['voltage'], params['current'], params['net']), (50, 4, NET))
            questions = {q['key']: q for q in first['questions']}
            self.assertEqual(set(questions), {'0.source_unit', '0.load_units'})
            self.assertEqual(questions['0.source_unit']['choices'][0], 'J4.1+J4.2')
            self.assertNotIn('J4.3', questions['0.source_unit']['choices'])
            self.assertTrue(questions['0.load_units']['choices'][0].startswith('U51.1+U51.2'))
            self.assertNotIn('U41.4', questions['0.load_units']['choices'][0])

            supplied = assistant.reply_answers(first, REPLY)
            self.assertEqual(supplied['0.source_unit'], 'J4.2')
            second = assistant.propose(QUERY, context, supplied, inventory=inventory())
            self.assertEqual(second['status'], 'ready', second)
            assistant.validate_plan(second)
            compiled = assistant._compile(second['steps'][0], context, Path(temporary) / 'out')
            self.assertIn('--batch', compiled['arguments'])
            study = compiled['documents']['settings.json']
            from quick_pi_plugin.batch import validate_study
            electrical = validate_study(study)['cases'][0]['electrical']
            self.assertEqual(electrical['source_terminals'], ['J4.2'])
            self.assertEqual(electrical['source_voltage'], 50)
            self.assertEqual([unit['label'] for unit in electrical['sinks']], ['U51', 'U52', 'U41'])
            for unit in electrical['sinks']:
                self.assertEqual(unit['current_A'], 4)
                self.assertEqual(unit['terminals'], [f"{unit['label']}.{index}" for index in (1,2,3,6)])
            self.assertEqual(sum(unit['current_A'] for unit in electrical['sinks']),12)

            confirm = assistant.reply_answers(first, 'Group all')
            self.assertEqual(confirm['0.source_unit'], 'J4.1+J4.2')
            self.assertEqual(assistant.propose(QUERY, context, confirm, inventory=inventory())['status'], 'ready')

            refine = assistant.reply_answers(second, 'Use J4.1 to U41.3')
            self.assertEqual(refine['0.source_unit'], 'J4.1')
            self.assertIn('U52.1+U52.2+U52.3+U52.6', refine['0.load_units'])
            self.assertTrue(refine['0.load_units'].endswith('U41.3'))
            self.assertFalse(assistant.reply_answers(second, 'run PI on GND from J4.3 to U51.4'))

    def test_total_current_is_not_reused_for_each_group(self):
        plan = assistant.propose('PI on PROTECTED_RAIL from J4.2 to U51.1 and U52.1 with 4 A total at 50 V',
                                 inventory=inventory())
        self.assertNotIn('current', plan['steps'][0]['params'])
        self.assertIn('0.current', {q['key'] for q in plan['questions']})

    def test_ambiguous_or_incomplete_load_list_never_becomes_one_load(self):
        plan = assistant.propose('PI from J4.2 to U51.1, U52, and U41 pins with 4 A each at 50 V',
                                 inventory=inventory())
        self.assertEqual(plan['steps'][0]['action'], 'quick-pi.grouped')
        self.assertEqual(plan['status'], 'needs_input')
        self.assertIn('0.load_units', {row['key'] for row in plan['questions']})

    def test_followups_can_change_only_the_named_side(self):
        plan = assistant.propose(QUERY, inventory=inventory())
        self.assertEqual(assistant.reply_answers(plan, 'source J4.2'), {'0.source_unit':'J4.2'})
        answer = assistant.reply_answers(plan, 'to U41 pins 1,2,3 and 6 and same pins on U51, and U52')
        self.assertNotIn('0.source_unit', answer)
        self.assertTrue(answer['0.load_units'].startswith('U51.1+U51.2+U51.3+U51.6'))

    def test_explicit_return_net_does_not_become_the_supply(self):
        plan = assistant.propose('PI from J4.2 to U51.1 and U52.1 with 4 A each at 50 V, return net GND',
                                 inventory=inventory())
        params = plan['steps'][0]['params']
        self.assertEqual(params['net'], NET)
        self.assertEqual(params['return_nets'], ['GND'])

    def test_wrong_net_and_duplicate_contact_require_correction(self):
        bad = assistant.propose(QUERY, answers={'source_unit':'J4.3','load_units':'U51.4 | U52.1'},
                                inventory=inventory())
        questions = {q['key']: q for q in bad['questions']}
        self.assertIn('different net', questions['0.source_unit']['error'])
        self.assertIn('different net', questions['0.load_units']['error'])
        with tempfile.TemporaryDirectory() as temporary:
            board = Path(temporary) / 'board.kicad_pcb'
            board.write_text('(kicad_pcb)')
            repeated = assistant.propose(QUERY, {'board':str(board)}, answers={
                'source_unit':'J4.2','load_units':'U51.1+U51.2 | U51.2'}, inventory=inventory())
            self.assertEqual(repeated['status'], 'needs_input')
            self.assertIn('only once', repeated['error'])

    def test_explicit_group_currents_and_source_connector(self):
        plan = assistant.propose('PI on PROTECTED_RAIL from J4 to U51.1 @ 250 mA | U52.1 @ 2 A at 50 V',
                                 inventory=inventory())
        fields = {q['key']: q for q in plan['questions']}
        self.assertIn('0.source_unit', fields)
        self.assertNotIn('0.current', fields)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board = root / 'board.kicad_pcb'
            board.write_text('(kicad_pcb)')
            context = {'board':str(board)}
            full = assistant.propose(plan['query'], context, {'source_unit':'J4.1+J4.2'},
                                     inventory=inventory())
            self.assertEqual(full['status'], 'ready', full)
            compiled = assistant._compile(full['steps'][0], context, root / 'out')
            loads = compiled['documents']['settings.json']['cases'][0]['electrical']['sinks']
            self.assertEqual([load['current_A'] for load in loads], [.25, 2])

    def test_single_bare_connector_can_offer_a_group(self):
        plan = assistant.propose('Quick PI on PROTECTED_RAIL from J4 to U51.1 at 50 V with 4 A',
                                 inventory=inventory())
        self.assertEqual(plan['steps'][0]['action'], 'quick-pi.grouped')
        choice = next(q for q in plan['questions'] if q['key']=='0.source_unit')
        self.assertEqual(choice['choices'][0], 'J4.1+J4.2')


if __name__ == '__main__':
    unittest.main()
