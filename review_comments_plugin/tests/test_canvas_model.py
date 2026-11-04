"""Pure viewport math and exact-scope, current-provider marker authorization."""
from copy import deepcopy
import math

import pytest

from review_comments_plugin.canvas_model import (
    Marker, Viewport, draft_point, draft_region, hit_test, markers_from_rows,
)
from review_comments_plugin.model import scope


SCOPE = dict(repository='owner/board', ref='a'*40, file='pcb/main.kicad_pcb')


def row(identifier='1', target=None, **metadata):
    return dict(id=identifier, body='Provider comment', anchors=[target or dict(SCOPE, position=dict(x=10, y=20))],
                **metadata)


def test_viewport_preserves_aspect_positive_svg_y_and_roundtrips():
    viewport = Viewport((10, -20, 100, 50), 800, 600)
    assert viewport.scale == 8
    assert viewport.project(10, -20) == (0, 100)
    assert viewport.project(110, 30) == (800, 500)
    assert viewport.project(20, 0)[1] > viewport.project(20, -10)[1]
    for point in ((10, -20), (70, 4), (110, 30)):
        assert viewport.unproject(*viewport.project(*point)) == pytest.approx(point)


def test_pan_zoom_anchors_cursor_and_resize_preserves_world_center():
    viewport = Viewport((-40, 30, 80, 120), 900, 700)
    original = viewport.project(4, 70)
    viewport.pan(35, -11)
    assert viewport.project(4, 70) == pytest.approx((original[0]+35, original[1]-11))
    cursor = (217, 443)
    under_cursor = viewport.unproject(*cursor)
    viewport.zoom(2.7, *cursor)
    assert viewport.project(*under_cursor) == pytest.approx(cursor)
    viewport.zoom(1/2.7, *cursor)
    assert viewport.unproject(*cursor) == pytest.approx(under_cursor)
    before = viewport.unproject(viewport.width/2, viewport.height/2)
    viewport.resize(500, 1000)
    assert viewport.unproject(250, 500) == pytest.approx(before)


def test_zoom_scale_is_bounded_and_zero_size_canvas_is_safe():
    viewport = Viewport((0, 0, 20, 10), 0, 0)
    viewport.zoom(1e15, 0, 0)
    assert viewport.scale == viewport.MAX_SCALE
    viewport.zoom(1e-15, 0, 0)
    viewport.zoom(1e-15, 0, 0)
    assert viewport.scale == viewport.MIN_SCALE
    viewport.pan(1e15, -1e15)
    viewport.pan(1e15, -1e15)
    assert abs(viewport.offset_x) <= viewport.MAX_OFFSET
    assert abs(viewport.offset_y) <= viewport.MAX_OFFSET
    assert all(math.isfinite(v) for v in viewport.unproject(1, 2))


@pytest.mark.parametrize('invalid', [math.nan, math.inf, -math.inf, True, '1', 10**500])
def test_viewport_rejects_nonfinite_or_non_numeric_actions(invalid):
    viewport = Viewport((0, 0, 20, 10), 800, 600)
    for action in (lambda: viewport.pan(invalid, 0), lambda: viewport.zoom(invalid, 1, 1),
                   lambda: viewport.project(invalid, 0), lambda: viewport.resize(invalid, 4)):
        with pytest.raises(ValueError):
            action()


@pytest.mark.parametrize('bounds', [(0, 0, 0, 1), (0, 0, -1, 10), (0, 0, 10, math.nan), (0, 1)])
def test_invalid_canvas_bounds_fail_explicitly(bounds):
    with pytest.raises(ValueError):
        Viewport(bounds, 800, 600)


def test_current_provider_points_regions_annotations_and_metadata_are_preserved_without_mutation():
    rows = [row('9', dict(SCOPE, area=dict(x=0, y=4, width=20, height=10))),
            dict(id='2', annotations=[dict(anchor=dict(SCOPE, position=dict(x=2, y=3)),
                 text='Review clearance', severity='warning', state='resolved')])]
    before = deepcopy(rows)
    markers, unplaced = markers_from_rows(rows, SCOPE, 'synced')
    assert not unplaced
    assert [marker.comment_id for marker in markers] == ['2', '9']
    assert (markers[0].x, markers[0].y, markers[0].severity, markers[0].state) == (2, 3, 'warning', 'resolved')
    assert markers[0].label == 'Review clearance'
    assert (markers[1].x, markers[1].y) == (10, 9)
    assert markers[1].region == (0, 4, 20, 10)
    assert scope(markers[1].anchor) == scope(SCOPE)
    assert rows == before
    markers[0].anchor['position']['x'] = 999
    assert rows == before


@pytest.mark.parametrize('status', ['not synced', 'cached / unverified', 'offline / stale', 'publication pending', 'synced '])
def test_cached_stale_or_ambiguous_publication_status_never_authorizes_overlay(status):
    markers, unplaced = markers_from_rows([row()], SCOPE, status)
    assert markers == [] and len(unplaced) == 1
    assert 'unverified' in unplaced[0]['reason']


@pytest.mark.parametrize('change', [dict(repository='other/board'), dict(ref='b'*40),
    dict(file='pcb/other.kicad_pcb'), dict(file='sheet/main.kicad_sch'),
    dict(provider='gitlab', host='https://gitlab.com')])
def test_foreign_provider_project_revision_or_file_stays_unplaced(change):
    target = dict(SCOPE, position=dict(x=1, y=2), **change)
    markers, unplaced = markers_from_rows([row(target=target)], SCOPE, 'synced')
    assert markers == []
    assert 'another provider' in unplaced[0]['reason']


def test_gitlab_host_is_part_of_scope_and_canonical_default_github_scope_matches():
    expected = dict(SCOPE, provider='gitlab', host='https://gitlab.example')
    foreign = dict(expected, host='https://other.example', position=dict(x=1, y=2))
    assert not markers_from_rows([row(target=foreign)], expected, 'synced')[0]
    github = dict(SCOPE, provider='github', position=dict(x=1, y=2))
    assert len(markers_from_rows([row(target=github)], SCOPE, 'synced')[0]) == 1


def test_uuid_resolution_requires_one_finite_position_and_never_chooses_a_duplicate():
    rows = [row(target=dict(SCOPE, uuid='saved-object'))]
    for position in ({'x': 3, 'y': 4}, (3, 4), [{'x': 3, 'y': 4}]):
        markers, unplaced = markers_from_rows(rows, SCOPE, 'synced', {'saved-object': position})
        assert not unplaced and (markers[0].x, markers[0].y) == (3, 4)
    for positions in (None, {}, {'saved-object': []},
                      {'saved-object': [{'x': 3, 'y': 4}, {'x': 3, 'y': 4}]},
                      {'saved-object': dict(x=math.inf, y=4)}):
        markers, unplaced = markers_from_rows(rows, SCOPE, 'synced', positions)
        assert markers == [] and unplaced[0]['comment_id'] == '1'


def test_explicit_position_does_not_fall_back_to_uuid_when_position_is_invalid():
    target = dict(SCOPE, uuid='saved-object', position=dict(x=math.nan, y=1))
    markers, unplaced = markers_from_rows([row(target=target)], SCOPE, 'synced', {'saved-object': (4, 5)})
    assert not markers and 'valid design anchor' in unplaced[0]['reason']


def test_duplicate_comment_identity_and_invalid_annotations_cannot_fall_back_to_cached_anchors():
    assert not markers_from_rows([row(), row()], SCOPE, 'synced')[0]
    supplied = row()
    supplied['annotations'] = []
    markers, unplaced = markers_from_rows([supplied], SCOPE, 'synced')
    assert not markers and 'valid design anchor' in unplaced[0]['reason']


def test_hit_testing_uses_pixel_radius_at_any_zoom_and_deterministic_pin_region_priority():
    viewport = Viewport((0, 0, 100, 100), 1000, 1000)
    target = draft_point(SCOPE, 20, 30)
    a = Marker('1', target, 20, 30)
    b = Marker('2', target, 20, 30)
    region = Marker('3', draft_region(SCOPE, 10, 10, 50, 50), 35, 35, region=(10, 10, 50, 50))
    assert hit_test([b, region, a], viewport, 207, 300) is a
    assert hit_test([b, a], viewport, 211, 300) is None
    assert hit_test([region], viewport, 120, 120) is region
    assert hit_test([region], viewport, 120, 120, include_regions=False) is None
    viewport.zoom(5, 200, 300)
    assert hit_test([a], viewport, 207, 300) is a
    assert hit_test([a], viewport, 211, 300) is None


def test_draft_anchors_are_exact_scope_and_validate_finite_positive_regions():
    assert draft_point(SCOPE, 1.5, -2)['position'] == dict(x=1.5, y=-2)
    region = draft_region(SCOPE, -4, 2, 10, 15)
    assert region['kind'] == 'region' and scope(region) == scope(SCOPE)
    for action in (lambda: draft_point(SCOPE, math.inf, 2), lambda: draft_point(SCOPE, True, 2),
                   lambda: draft_region(SCOPE, 0, 0, 0, 10), lambda: draft_region(SCOPE, 0, 0, -1, 10)):
        with pytest.raises(ValueError):
            action()
