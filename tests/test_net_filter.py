"""Shared net-name search and selected-net preservation contracts."""
import unittest

from wayricad_runtime.net_filter import filter_combo, matching_nets


class _Combo:
    def __init__(self, value=''):
        self.value = value
        self.items = []
    def GetValue(self):
        return self.value
    def Set(self, items):
        self.items = list(items)
        self.value = ''
    def SetValue(self, value):
        self.value = value
    def SetSelection(self, index):
        self.value = self.items[index] if index >= 0 else ''


class NetFilterTests(unittest.TestCase):
    def test_literal_substring_casefold_and_wildcards(self):
        names = ['/Top/U1/DATA[0]', '/Top/U1/DATA[1]', '/Top/U1/CLK_P']
        self.assertEqual(matching_nets(names, 'data[0]'), [names[0]])
        self.assertEqual(matching_nets(names, 'DATA[*]'), names[:2])
        self.assertEqual(matching_nets(names, 'DATA[?]'), names[:2])
        self.assertEqual(matching_nets(names, 'DATA[*]', mode='literal'), [])
        self.assertEqual(matching_nets(names, ''), names)

    def test_fuzzy_mode_is_explicit_and_rank_is_stable(self):
        names = ['/z/CLX', '/a/CLY', '/exact/CLK']
        self.assertEqual(matching_nets(names, 'CLK'), ['/exact/CLK'])
        self.assertEqual(matching_nets(names, '~CLK'), ['/exact/CLK', '/a/CLY', '/z/CLX'])
        self.assertEqual(matching_nets(names, 'CLY', mode='fuzzy'), ['/a/CLY', '/exact/CLK', '/z/CLX'])

    def test_query_never_creates_selection_and_existing_choice_stays_pinned(self):
        names = ['CAN_P', 'CAN_N', 'USB[0]']
        combo = _Combo('CAN_P')
        self.assertEqual(filter_combo(combo, names, 'usb'), ['CAN_P', 'USB[0]'])
        self.assertEqual(combo.value, 'CAN_P')
        self.assertEqual(filter_combo(combo, names, 'not-a-net'), ['CAN_P'])
        self.assertEqual(combo.value, 'CAN_P')
        combo.value = ''
        self.assertEqual(filter_combo(combo, names, 'not-a-net'), [])
        self.assertEqual(combo.value, '')

    def test_large_inventory_query_returns_exact_original_names(self):
        names = [f'/Board/Block{i // 100}/NET_{i:05d}_CLK' for i in range(10_000)]
        result = matching_nets(names, 'net_09999_clk')
        self.assertEqual(result, [names[-1]])

    def test_large_hierarchical_fuzzy_search_ranks_typo_target_and_is_capped(self):
        names = [
            f'/Project/Board/Controller/Channel{i // 100}/NET_{i:05d}_CLK'
            for i in range(10_000)
        ]
        result = matching_nets(names, '~NET_09998_CLK')
        self.assertEqual(result[0], names[9998])
        self.assertLessEqual(len(result), 100)
        self.assertEqual(result, matching_nets(names, '~NET_09998_CLK'))


if __name__ == '__main__':
    unittest.main()
