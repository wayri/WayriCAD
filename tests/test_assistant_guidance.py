import unittest

from wayricad_runtime.assistant_context import CircuitInventory
from wayricad_runtime.assistant_guidance import completions, context_net, guidance


class AssistantGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.inventory = CircuitInventory(
            ('/Power stage/VBUS', 'GND', '/A/EN', '/B/EN'),
            {'J1': 'Connector', 'J2': 'Connector', 'U1': 'Regulator'},
            {
                'J1.1': {'GND'}, 'J1.2': {'/Power stage/VBUS'},
                'J1.3': {'/Power stage/VBUS'}, 'J2.1': {'GND'},
                'U1.6': {'/Power stage/VBUS'}, 'U1.7': {'/Power stage/VBUS'},
            },
        )

    def test_connector_context_lists_only_pads_on_the_named_net(self):
        result = guidance('Which pins on J1 and U1 are on VBUS?', self.inventory)
        self.assertIn('/Power stage/VBUS', result)
        self.assertIn('J1.2, J1.3', result)
        self.assertIn('U1.6, U1.7', result)
        self.assertIn('possible pad group', result)
        self.assertNotIn('J1.1', result)

    def test_short_names_do_not_choose_an_ambiguous_net(self):
        self.assertIsNone(context_net('Which pins are on EN?', self.inventory))
        self.assertEqual(context_net('Which pads use "/Power stage/VBUS"?', self.inventory), '/Power stage/VBUS')
        self.assertEqual(context_net('Which pins are on this net?', self.inventory, active_net='GND'), 'GND')

    def test_study_requests_still_go_through_the_typed_plan(self):
        self.assertIsNone(guidance('Can you run Quick PI from J1 to U1 on VBUS?', self.inventory))
        self.assertIn('Quick SI', guidance('Which plugin handles crosstalk?'))
        self.assertIn('effective capacitance', guidance('How should I model bypass capacitors in a load step?'))

    def test_net_recommendations_use_shared_native_connectivity(self):
        result = guidance('Which nets connect J1 and U1?', self.inventory)
        self.assertIn('Shared saved nets · /Power stage/VBUS', result)
        self.assertIn('J1 · /Power stage/VBUS, GND', result)

    def test_completion_prioritizes_rail_pads_without_hiding_other_names(self):
        rows = completions(self.inventory, 'J1.', '/Power stage/VBUS')
        self.assertEqual([row[1] for row in rows], ['J1.2', 'J1.3', 'J1.1'])
