import math

import pytest

from planar_magnetics_plugin.motor_layout import annular_coil_paths
from planar_magnetics_plugin.motor_model import synthesize_winding


def test_three_phase_annular_preview_projects_each_balanced_coil():
    winding = synthesize_winding(36, 4, 3, 9, 10)
    paths = annular_coil_paths(winding, 10, 35)
    assert len(paths) == 36
    assert {path["phase"] for path in paths} == {0, 1, 2}
    assert all(path["points_mm"][0] == path["points_mm"][-1] for path in paths)
    for path in paths:
        assert path["end_slot"] == (path["start_slot"] - 1 + 9) % 36 + 1
        assert path["polarity"] in (-1, 1)
        assert 10 < path["inner_radius_mm"] < path["outer_radius_mm"] < 35
        for x, y in path["points_mm"]:
            assert 10 < math.hypot(x, y) < 35
    lanes = {phase: (min(path["inner_radius_mm"] for path in paths if path["phase"] == phase),
                     max(path["outer_radius_mm"] for path in paths if path["phase"] == phase))
             for phase in range(3)}
    assert lanes[0][1] < lanes[1][0] < lanes[1][1] < lanes[2][0]


@pytest.mark.parametrize("inner,outer", [(0, 35), (35, 35), (36, 35), (float("nan"), 35), (10, float("inf"))])
def test_annular_preview_rejects_invalid_dimensions(inner, outer):
    winding = synthesize_winding(36, 4, 3, 9)
    with pytest.raises(ValueError, match="radii"):
        annular_coil_paths(winding, inner, outer)


def test_annular_preview_rejects_mismatched_end_slot():
    winding = synthesize_winding(36, 4, 3, 9)
    winding["coils"][0]["end_slot"] = 2
    with pytest.raises(ValueError, match="pitch"):
        annular_coil_paths(winding, 10, 35)
