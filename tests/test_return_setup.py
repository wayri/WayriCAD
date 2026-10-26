"""Name suggestions and endpoint-pad discovery never silently assign returns."""
import unittest

from wayricad_runtime.return_setup import suggest_return_nets, return_pad_candidates


class ReturnSetupTests(unittest.TestCase):
    def test_candidates_are_ranked_distinct_and_exclude_signal(self):
        rows = suggest_return_nets(['GND', 'GND', '/Power/PGND', '/Logic/GND', 'VCC', 'DGND', 'GND_SENSE'], 'DGND')
        self.assertEqual([r['name'] for r in rows], ['GND', '/Logic/GND', '/Power/PGND', 'GND_SENSE'])
        self.assertTrue(all('confirm' in r['reason'] for r in rows))

    def test_no_guess_from_arbitrary_net_or_substring(self):
        self.assertEqual(suggest_return_nets(['VCC', '/RESET', 'NOTGROUND', 'BACKGROUND']), [])

    def test_endpoint_filter_keeps_identity_and_duplicate_pads(self):
        terminals = [{'id': 'one', 'label': 'U1.2', 'net': 'GND'},
                     {'id': 'two', 'label': 'U1.2', 'net': 'GND'},
                     {'id': 'three', 'label': 'U2.2', 'net': 'GND'},
                     {'id': 'four', 'label': 'U1.1', 'net': 'VCC'}]
        rows = return_pad_candidates(terminals, ['GND'], reference='U1')
        self.assertEqual([r['id'] for r in rows], ['one', 'two'])
        rows[0]['net'] = 'CHANGED'
        self.assertEqual(terminals[0]['net'], 'GND')

    def test_no_selected_net_means_no_pads(self):
        self.assertEqual(return_pad_candidates([{'id': 'one', 'net': 'GND'}], []), [])
