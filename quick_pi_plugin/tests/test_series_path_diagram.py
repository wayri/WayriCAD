"""Schematic lanes preserve reviewed banks; wire lengths require saved evidence."""
from copy import deepcopy
import json
import sys
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from quick_pi_plugin.series_path_diagram import copper_lengths, diagram_layout, diagram_svg
from quick_pi_plugin.series_power_tree import build_series_power_tree, series_path_tree, tree_text
from quick_pi_plugin.tests.test_series_power_tree import fixture, solved_bundle


def copper():
    return dict(net='VIN', incoming_pins=[dict(id='a', label='J1.1')],
                outgoing_pins=[dict(id='b', label='Q1.1')])


def evidence():
    return dict(pads={'a': dict(position_mm=[0, 0], layers=[0], net='VIN'),
                      'b': dict(position_mm=[3, 4], layers=[0], net='VIN')},
                tracks=[dict(net='VIN', layer=0, start_mm=[0, 0], end_mm=[3, 0], length_mm=3),
                        dict(net='VIN', layer=0, start_mm=[3, 0], end_mm=[3, 4], length_mm=4)])


def test_length_uses_saved_centerline_chain_and_reports_straight_estimate_separately():
    data = evidence(); original = deepcopy(data)
    length = copper_lengths(copper(), data)[0]
    assert length['status'] == 'saved_track_chain'
    assert length['length_mm'] == 7
    assert 'shortest planar saved track/arc chain' in length['label']
    assert data == original
    data['tracks'].pop()
    estimate = copper_lengths(copper(), data)[0]
    assert estimate['status'] == 'estimated_straight_distance'
    assert estimate['length_mm'] == 5
    assert 'routed length unknown' in estimate['label']
    unknown = copper_lengths(copper(), {})[0]
    assert unknown['length_mm'] is None
    assert unknown['status'] == 'unavailable'


def test_saved_arc_length_is_not_replaced_by_its_chord_or_another_net_or_layer():
    data = evidence()
    data['tracks'] = [dict(net='VIN', layer=0, start_mm=[0, 0], end_mm=[3, 4], length_mm=8)]
    assert copper_lengths(copper(), data)[0]['length_mm'] == 8
    for key, value in (('net', 'OTHER'), ('layer', 2), ('length_mm', 1)):
        changed = deepcopy(data)
        changed['tracks'][0][key] = value
        length = copper_lengths(copper(), changed)[0]
        assert length['status'] == 'estimated_straight_distance'
        assert length['length_mm'] == 5


def test_coincident_pads_without_saved_chain_do_not_claim_routed_length():
    data = evidence()
    data['pads']['b']['position_mm'] = [0, 0]
    data['tracks'] = []
    assert copper_lengths(copper(), data)[0]['status'] == 'estimated_straight_distance'


def test_all_parallel_parts_pin_groups_nets_and_explicit_unknowns_appear_in_svg():
    saved, path, _ = fixture()
    tree = series_path_tree(path, saved)
    original = deepcopy(tree)
    drawing = diagram_layout(tree)
    assert sum(c['kind'] == 'rect' for c in drawing['commands']) == 4
    assert drawing['height'] < 950  # Two complete banks need only modest vertical scrolling.
    svg = diagram_svg(tree)
    ElementTree.fromstring(svg)
    for value in ('VIN', 'MID', 'OUT', 'Q1', 'Q2', 'Q3', 'Q4', 'Q1.1', 'Q1.2',
                  'Q4.3', 'Q4.4', 'J1.2', 'J2.2', 'wire length unavailable'):
        assert value in svg
    assert 'Q1.5' not in svg
    assert tree == original
    assert json.loads(json.dumps(tree, allow_nan=False)) == tree


def test_canvas_summarizes_length_evidence_while_details_retain_every_pad_pair():
    from quick_pi_plugin.series_path_diagram import wire_length_summary
    tree = build_series_power_tree(solved_bundle())
    segment = next(node for node in tree['nodes'] if node['kind'] == 'copper')
    segment['wire_lengths'] = [dict(from_pad='a', to_pad=str(index), length_mm=length,
        status=status, label='Unique pair evidence ' + str(index)) for index, (length, status) in enumerate([
            (8., 'saved_track_chain'), (12., 'saved_track_chain'),
            (5., 'estimated_straight_distance'), (9., 'estimated_straight_distance'),
            (None, 'unavailable')])]
    before = deepcopy(tree)
    summary = wire_length_summary(segment)
    assert 'Saved track chains: 2 pad pair(s), 8–12 mm' in summary
    assert 'Estimated straight distance: 2 pad pair(s), 5–9 mm (routed length unknown)' in summary
    assert 'wire length unavailable: 1 pad pair(s)' in summary
    svg = diagram_svg(tree)
    assert 'Unique pair evidence' not in svg
    for pair in segment['wire_lengths']:
        assert pair['label'] in tree_text(tree)
    assert tree == before


def test_solved_diagram_reuses_current_and_loss_without_inventing_wire_length():
    tree = build_series_power_tree(solved_bundle())
    svg = diagram_svg(tree)
    assert 'I 1.33333 A' in svg and 'I 0.666667 A' in svg
    assert 'R 0.1 Ω' in svg and 'R 0.2 Ω' in svg
    assert 'Vin 3.28 V' in svg and 'Vout 3.14667 V' in svg
    assert 'V 3.3 V' in svg
    assert 'loss' in svg
    assert 'wire length unavailable' in svg


@pytest.mark.parametrize('model, expected', [
    (dict(model='resistance', resistance_ohm=.125), ('resistance', 'R 0.125 Ω')),
    (dict(model='rl', resistance_ohm=.02, inductance_h=1e-8), ('rl', 'R 0.02 Ω', 'L 1e-08 H')),
    (dict(model='fixed_drop', fixed_drop_v=.7), ('fixed_drop', 'Vf 0.7 V')),
    (dict(model='diode', diode=dict(vf_ref_v=.65, reference_current_a=2., ideality=1.8, temperature_c=40.)),
     ('diode', 'Vf=0.65V', 'Iref=2A', 'n=1.8', 'T=40C')),
])
def test_model_type_never_hides_entered_numeric_parameters(model, expected):
    tree = build_series_power_tree(solved_bundle())
    stage = next(node for node in tree['nodes'] if node['kind'] == 'parallel_stage')
    stage['parts'][0]['model'] = model
    svg = diagram_svg(tree)
    for value in expected:
        assert value in svg


def test_inspected_path_geometry_flows_to_tree_text_and_literal_svg():
    saved, path, _ = fixture()
    data = evidence()
    data['pads'] = {'J1-1': data['pads']['a'], 'Q1-1': data['pads']['b']}
    saved['path_geometry'] = data
    tree = series_path_tree(path, saved)
    segment = next(node for node in tree['nodes'] if node['kind'] == 'copper')
    assert segment['wire_lengths'][0]['length_mm'] == 7
    assert '7 mm' in tree_text(tree)
    tree['nodes'][0]['label'] = '<Source & supply>'
    svg = diagram_svg(tree)
    assert '&lt;Source &amp; supply&gt;' in svg
    ElementTree.fromstring(svg)


def test_svg_export_uses_guarded_publication_and_separate_extension(tmp_path):
    from quick_pi_plugin.series_power_tree_ui import save_diagram
    tree = build_series_power_tree(solved_bundle())
    source = tmp_path / 'Example.kicad_pcb'
    source.write_text('saved board', encoding='utf-8')
    target = tmp_path / 'path.svg'
    checked = []
    save_diagram(target, tree, sources=[source], source_guard=lambda: checked.append(True))
    assert checked
    ElementTree.fromstring(target.read_text(encoding='utf-8'))
    with pytest.raises(ValueError, match='.svg'):
        save_diagram(source, tree, sources=[source], source_guard=lambda: None)
    assert source.read_text(encoding='utf-8') == 'saved board'
    def stale():
        raise ValueError('changed')
    previous = target.read_bytes()
    with pytest.raises(ValueError, match='changed'):
        save_diagram(target, tree, sources=[source], source_guard=stale)
    assert target.read_bytes() == previous


def test_native_saved_geometry_reads_exact_tracks_and_pad_centers():
    pcbnew = pytest.importorskip('pcbnew')
    from quick_pi_plugin.series_path_diagram import saved_path_geometry
    board = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(board, 'VIN'); board.Add(net)
    fp = pcbnew.FOOTPRINT(board); fp.SetReference('J1'); board.Add(fp)
    pad = pcbnew.PAD(fp); pad.SetNumber('1'); pad.SetNet(net)
    pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(1), pcbnew.FromMM(2))); fp.Add(pad)
    track = pcbnew.PCB_TRACK(board); track.SetNet(net); track.SetLayer(pcbnew.F_Cu)
    track.SetStart(pcbnew.VECTOR2I(0, 0)); track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(3), pcbnew.FromMM(4)))
    board.Add(track)
    before = (len(list(board.GetTracks())), len(list(board.GetFootprints())),
              pad.GetPosition().x, pad.GetPosition().y, track.GetLength())
    data = saved_path_geometry(board)
    assert data['pads'][pad.m_Uuid.AsString()]['position_mm'] == [1, 2]
    assert data['tracks'][0]['length_mm'] == pytest.approx(5)
    assert (len(list(board.GetTracks())), len(list(board.GetFootprints())),
            pad.GetPosition().x, pad.GetPosition().y, track.GetLength()) == before


@pytest.mark.parametrize('board', [SimpleNamespace(GetFootprints=lambda: []),
    SimpleNamespace(GetFootprints=lambda: [], GetTracks=lambda: [], GetEnabledLayers=lambda: None)])
def test_optional_path_evidence_does_not_require_native_geometry_for_portable_solvers(board, monkeypatch):
    from quick_pi_plugin.series_path_diagram import saved_path_geometry
    monkeypatch.setitem(sys.modules, 'pcbnew', None)
    data = saved_path_geometry(board)
    assert data['status'] == 'unavailable'
    assert data['pads'] == {} and data['tracks'] == []
    assert 'unknown' in data['notice']
    lengths = copper_lengths(copper(), data)
    assert lengths[0]['status'] == 'unavailable' and lengths[0]['length_mm'] is None


_APP = None


def test_native_canvas_keeps_complete_large_banks_scrollable_without_raster_images():
    wx = pytest.importorskip('wx')
    from quick_pi_plugin.series_power_tree_ui import diagram_canvas
    global _APP
    _APP = wx.GetApp() or wx.App(False)
    frame = wx.Frame(None)
    try:
        tree = build_series_power_tree(solved_bundle())
        stage = next(node for node in tree['nodes'] if node['kind'] == 'parallel_stage')
        stage['parts'] = stage['parts'] * 20
        canvas = diagram_canvas(frame, tree)
        canvas.SetSize(frame.FromDIP((960, 600)))
        canvas.fit_width()
        assert canvas.GetVirtualSize().width <= canvas.GetClientSize().width
        assert .75 <= canvas.scale <= 1.
        canvas.SetSize((700, 400))
        canvas.fit_width()
        assert canvas.GetVirtualSize().height > canvas.GetClientSize().height * 5
        assert canvas.GetVirtualSize().width > canvas.GetClientSize().width
        canvas.Scroll(20, 1000)
        assert canvas.GetViewStart()[0] > 0 and canvas.GetViewStart()[1] > 0
    finally:
        frame.Destroy()
