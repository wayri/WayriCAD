"""Circuit export must not silently discard off-path copper."""
from types import SimpleNamespace
import unittest

from signal_integrity_advisor_plugin.circuit_scope import circuit_topology


def item(identifier, length=10, net='DATA', kind='PCB_TRACK'):
    return SimpleNamespace(m_Uuid=SimpleNamespace(AsString=lambda: identifier),
                           GetLength=lambda: length * 1e6, GetNetname=lambda: net,
                           GetClass=lambda: kind)


class CircuitScopeTests(unittest.TestCase):
    def check(self, tracks, sections, terminals=2, zones=()):
        board=SimpleNamespace(GetTracks=lambda: tracks, Zones=lambda: zones)
        path=SimpleNamespace(net_name='DATA', status='partial', segments=sections)
        return circuit_topology(board,path,terminals)

    def test_complete_track_via_channel_ignores_other_nets(self):
        tracks=[item('a'),item('v',0,kind='PCB_VIA'),item('b',5),item('g',net='GND')]
        sections=[dict(item_uuid='a',length_mm=10,kind='track'),
                  dict(item_uuid='v',length_mm=1.6,kind='via'),
                  dict(item_uuid='b',length_mm=5,kind='track')]
        self.assertTrue(self.check(tracks,sections)['complete'])

    def test_two_terminal_net_with_stub_is_not_complete(self):
        result=self.check([item('a'),item('stub',1)],
                          [dict(item_uuid='a',length_mm=10,kind='track')])
        self.assertFalse(result['complete'])
        self.assertEqual(result['unmodeled_item_uuids'],['stub'])

    def test_partial_same_uuid_and_additional_terminal_reject(self):
        section=[dict(item_uuid='a',length_mm=5,kind='track')]
        self.assertTrue(self.check([item('a')],section)['length_mismatches'])
        self.assertFalse(self.check([item('a',5)],section,3)['complete'])

    def test_zones_unknown_lengths_and_ambiguous_ids_reject(self):
        section=[dict(item_uuid='a',length_mm=10,kind='track')]
        for tracks,zones in (([item('a')],[item('z')]),
                             ([item('a'),item('a')],[]),
                             ([item('a',float('nan'))],[])):
            with self.subTest(tracks=tracks,zones=zones):
                self.assertFalse(self.check(tracks,section,zones=zones)['complete'])

    def test_native_track_cannot_be_reclassified_as_via_to_hide_length(self):
        result=self.check([item('track',20)],
                          [dict(item_uuid='track',length_mm=1,kind='via')])
        self.assertFalse(result['complete'])
        self.assertIn('differs from its native',result['notes'][0])


if __name__=='__main__':unittest.main()
