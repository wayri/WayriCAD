"""Explicit connector poses and physical tables preserve contact identity."""
import copy
from types import SimpleNamespace

import pytest

from extract_pins_plugin.core.connector_mating import (
    footprint_pins, grid_text, match_mating, physical_grid, transform_pins,
)


def pin(number, x, y, label=None):
    return dict(pin=str(number), label=label or 'NET_'+str(number), x_mm=x, y_mm=y)


def connector():
    return [pin(1, 10, 20), pin(2, 12, 20), pin(3, 10, 22), pin(4, 12, 22)]


def numbers(grid):
    return [[p['pin'] if p else None for p in row] for row in grid]


def test_physical_tables_follow_geometry_not_numeric_sort():
    pins = [pin(6, 10, 20), pin(1, 12, 20), pin(5, 10, 22), pin(2, 12, 22)]
    assert numbers(physical_grid(reversed(pins))) == [['6', '1'], ['5', '2']]
    assert numbers(physical_grid(pins, side='bottom')) == [['1', '6'], ['2', '5']]
    assert numbers(physical_grid(pins, rotation_deg=90)) == [['5', '6'], ['2', '1']]
    assert numbers(physical_grid(pins, side='bottom', mirror=True)) == [['6', '1'], ['5', '2']]


def test_sparse_rows_columns_holes_and_small_native_rounding_are_preserved():
    pins = [pin('A1', 0, 0), pin('A3', 4, .000001), pin('B2', 2, 2), pin('B3', 4, 2)]
    grid = physical_grid(pins)
    assert numbers(grid) == [['A1', None, 'A3'], [None, 'B2', 'B3']]
    assert grid_text(grid).splitlines()[0] == 'A1: NET_A1,,A3: NET_A3'
    assert '| Column 1 | Column 2 | Column 3 |' in grid_text(grid, 'md')


def test_grid_does_not_chain_merge_points_outside_tolerance():
    pins = [pin(1, 0, 0), pin(2, .015, 1), pin(3, .03, 2)]
    assert numbers(physical_grid(pins, tolerance_mm=.02)) == [['1', None], ['2', None], [None, '3']]


def test_axis_rotation_and_translation_do_not_mutate_data():
    source = connector(); saved = copy.deepcopy(source)
    posed = transform_pins(source, side='bottom', rotation_deg=90, x_mm=7, y_mm=8)
    for actual, expected in zip(posed, [(8, 9), (8, 7), (6, 9), (6, 7)]):
        assert (actual['x_mm'], actual['y_mm']) == pytest.approx(expected)
    assert source == saved
    assert [p['pin'] for p in posed] == ['1', '2', '3', '4']
    posed[0]['label'] = 'CHANGED'
    assert source == saved


def test_default_facing_preset_and_explicit_bottom_have_same_mapping():
    source = connector()
    result = match_mating(source, source)
    assert [(r['a']['pin'], r['b']['pin']) for r in result['pairs']] == [('1','2'), ('2','1'), ('3','4'), ('4','3')]
    assert not result['issues']
    bottom = match_mating(source, source, pose_b={'side': 'bottom'})
    assert bottom == result
    unchanged = match_mating(source, source, pose_b={})
    assert [(r['a']['pin'], r['b']['pin']) for r in unchanged['pairs']] == [('1','1'), ('2','2'), ('3','3'), ('4','4')]


def test_asymmetric_rotation_matches_positions_not_pin_numbers():
    a = [pin('1', 0, 0), pin('2', 1, 0), pin('3', 0, 2)]
    b = [pin('A', 0, 0), pin('B', 0, 1), pin('C', -2, 0)]
    result = match_mating(a, b, pose_b={'rotation_deg': -90})
    assert [(r['a']['pin'],r['b']['pin']) for r in result['pairs']] == [('1','A'),('2','B'),('3','C')]
    assert not result['unmatched_a'] and not result['unmatched_b']
    offset = match_mating(a, b, pose_b={'rotation_deg': -90, 'x_mm': 10})
    assert not offset['pairs'] and len(offset['unmatched_a']) == 3


def test_ambiguous_contacts_are_never_resolved_greedily():
    a = [pin('1', -.01, 0), pin('2', .01, 0)]
    b = [pin('A', -.02, 0), pin('B', .02, 0)]
    result = match_mating(a, b, tolerance_mm=.1, pose_b={})
    assert not result['pairs']
    assert len(result['unmatched_a']) == len(result['unmatched_b']) == 2
    assert any('multiple' in issue for issue in result['issues'])


def test_partial_mating_retains_every_missing_contact_and_existing_net():
    source = connector()
    target = source + [pin(5, 11, 21, 'OTHER')]
    result = match_mating(source, target, pose_b={})
    assert len(result['pairs']) == 4
    assert not result['unmatched_a']
    assert result['unmatched_b'][0]['pin'] == '5'
    assert result['unmatched_b'][0]['label'] == 'OTHER'


def test_invalid_duplicates_coordinates_and_grid_collisions_are_refused():
    for invalid in ([pin(1, 0, 0), pin(1, 1, 0)], [pin(1, float('nan'), 0)], [dict(pin='', x_mm=0, y_mm=0)]):
        with pytest.raises(ValueError):transform_pins(invalid)
    with pytest.raises(ValueError, match='one grid cell'):
        physical_grid([pin(1, 0, 0), pin(2, .01, 0)])
    with pytest.raises(ValueError, match='finite'):
        transform_pins(connector(), rotation_deg=float('inf'))
    with pytest.raises(ValueError, match='side'):
        transform_pins(connector(), side='rear')
    with pytest.raises(ValueError, match='Unknown'):
        match_mating(connector(), connector(), pose_a={'scale': 2})


def test_size_and_irregular_grid_budgets_are_actionable():
    with pytest.raises(ValueError, match='2000'):
        transform_pins(pin(i, i, 0) for i in range(2001))
    with pytest.raises(ValueError, match='10,000'):
        physical_grid([pin(i, i, i) for i in range(101)])
    with pytest.raises(ValueError, match='positive'):
        match_mating(connector(), connector(), tolerance_mm=0)
    with pytest.raises(ValueError, match='too small'):
        match_mating(connector(), connector(), tolerance_mm=1e-320)


class Pad:
    def __init__(self, number, x, y, net):
        self.number=number;self.position=SimpleNamespace(x=x,y=y);self.net=net
    def GetNumber(self):return self.number
    def GetPosition(self):return self.position
    def GetNetname(self):return self.net


def test_native_adapter_ignores_mechanics_and_accepts_only_identical_repeated_lands():
    pads = [Pad('',0,0,''), Pad('1',1000000,2000000,'GND'), Pad('1',1000000,2000000,'GND')]
    footprint=SimpleNamespace(Pads=lambda:pads)
    assert footprint_pins(footprint) == [pin('1',1,2,'GND')]
    pads.append(Pad('1',2000000,2000000,'GND'))
    with pytest.raises(ValueError, match='multiple positions'):
        footprint_pins(footprint)


def test_empty_connectors_are_not_a_successful_mating():
    assert physical_grid([]) == []
    assert grid_text([]) == ''
    assert match_mating([], [])['issues']


def test_markdown_and_csv_preserve_labels_without_html_or_delimiter_breakout():
    pins = [dict(pin=0, label='<tag>|A,B\nC', x_mm=0, y_mm=0)]
    grid = physical_grid(pins)
    assert grid[0][0]['pin'] == '0'
    assert '0: &lt;tag&gt;\\|A,B<br>C' in grid_text(grid, 'markdown')
    import csv
    from io import StringIO
    assert list(csv.reader(StringIO(grid_text(grid)))) == [['0: <tag>|A,B\nC']]
