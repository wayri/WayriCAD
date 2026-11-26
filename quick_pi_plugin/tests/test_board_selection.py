import unittest
from quick_pi_plugin.board_selection import selection_plan
from wayricad_runtime.selection_follow import SelectionState


class BoardSelectionTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {'nets': ['VCC', 'GND'], 'terminals': [
            {'id': 'a', 'label': 'U1.1', 'net': 'VCC'},
            {'id': 'b', 'label': 'U2.1', 'net': 'VCC'}]}
        self.scene = {'primitives': [
            {'uuid': 'a', 'parent_uuid': 'u1', 'net': 'VCC'},
            {'uuid': 'g', 'parent_uuid': 'u1', 'net': 'GND'},
            {'uuid': 't', 'net': 'VCC'}]}

    def test_copper_sets_net_but_never_guesses_direction(self):
        self.assertEqual(selection_plan(['T'], self.inventory, self.scene)['net'], 'VCC')
        with self.assertRaisesRegex(ValueError, 'exactly one pad'):
            selection_plan(['t'], self.inventory, self.scene, 'source')

    def test_explicit_pad_role_and_ambiguous_footprint(self):
        self.assertEqual(selection_plan(['a'], self.inventory, self.scene, 'sink')['terminal'], 'a')
        for identifiers in (['u1'], ['a', 'g'], ['unknown'], ['a', 'unknown']):
            with self.assertRaises(ValueError):
                selection_plan(identifiers, self.inventory, self.scene)
        with self.assertRaises(ValueError):
            selection_plan(['a', 'b'], self.inventory, self.scene, 'source')

    def test_follow_clear_only_for_opted_in_overlays(self):
        legacy,overlay=SelectionState(),SelectionState()
        self.assertTrue(legacy.changed(['a'],0))
        self.assertTrue(overlay.changed(['a'],0,include_empty=True))
        self.assertFalse(legacy.changed([],0))
        self.assertTrue(overlay.changed([],0,include_empty=True))
        self.assertFalse(overlay.changed([],0,include_empty=True))

    def test_follow_latest_epoch_and_disposal(self):
        state = SelectionState()
        self.assertTrue(state.changed(['A'], 0))
        self.assertFalse(state.changed(['a'], 0))
        state.reset()
        self.assertFalse(state.changed(['b'], 0))
        self.assertTrue(state.changed(['b'], 1))
        state.closed = True
        self.assertFalse(state.changed(['c'], 1))
