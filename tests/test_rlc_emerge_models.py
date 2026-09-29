"""Independent reference cases for the EMerge-derived RLC cross sections."""

import json
import math
import subprocess
import sys

import pytest

from trace_impedance_plugin import emerge_lines
from trace_impedance_plugin.cross_section import estimate
from trace_impedance_plugin.rlc_model import solve


@pytest.mark.parametrize("topology,call,expected", [
    ("microstrip", lambda: emerge_lines.microstrip(2.9, 1.53, .035, 4.5)[0], 49.7529184555),
    ("stripline", lambda: emerge_lines.stripline(.6, 1.53, .035, 4.5)[0], 50.5901060167),
    ("cpw", lambda: emerge_lines.coplanar(1.5, .3, 1.53, 4.5)[0], 57.6428853981),
    ("grounded-cpw", lambda: emerge_lines.coplanar(1.5, .3, 1.53, 4.5, backside_ground=True)[0], 50.9420598768),
    ("edge-coupled-stripline", lambda: emerge_lines.edge_coupled_stripline(.2, .2, .8, 4.2), 108.4950706800),
])
def test_independent_emerge_reference_cases(topology, call, expected):
    assert call() == pytest.approx(expected, rel=1e-8), topology


def test_board_solver_uses_corrected_emerge_models():
    micro = solve(2.9, 1.53, .035, 4.5, 30, topology="microstrip")
    strip = solve(.6, 1.53, .035, 4.5, 30, topology="stripline")
    assert micro["z0_ohm"] == pytest.approx(49.7529184555, rel=1e-8)
    assert strip["z0_ohm"] == pytest.approx(50.5901060167, rel=1e-8)
    assert micro["model"].startswith("EMerge")
    assert micro["effective_permittivity"] == pytest.approx(3.36986364336, rel=1e-8)


def test_cpw_and_pair_require_explicit_supported_geometry():
    cpw = estimate("grounded-cpw", 1.5, 1.53, 4.5, gap_mm=.3)
    assert cpw["single_ended_z0_ohm"] == pytest.approx(50.9420598768, rel=1e-8)
    pair = estimate("edge-coupled-stripline", .2, .8, 4.2, gap_mm=.2)
    assert pair["differential_z0_ohm"] == pytest.approx(108.4950706800, rel=1e-8)
    with pytest.raises(ValueError, match="zero copper thickness"):
        estimate("grounded-cpw", 1.5, 1.53, 4.5, copper_mm=.035, gap_mm=.3)
    with pytest.raises(ValueError, match="measured pair or lateral-ground gap"):
        estimate("edge-coupled-stripline", .2, .8, 4.2)
    with pytest.raises(ValueError, match="Unsupported"):
        estimate("differential-cpw", .2, .8, 4.2, gap_mm=.2)


def test_wide_line_and_invalid_material_fail_closed():
    with pytest.raises(ValueError):
        emerge_lines.microstrip(20, .1, .035, 4.2)
    with pytest.raises(ValueError):
        emerge_lines.stripline(20, .1, .035, 4.2)
    with pytest.raises(ValueError):
        emerge_lines.microstrip(.2, .2, .035, .8)
    assert math.isfinite(emerge_lines.stripline(.6, 1.53, .035, 4.5)[0])


def test_boardless_cross_section_cli_runs_without_pcbnew():
    command = [sys.executable, "-m", "trace_impedance_plugin.cli", "cross-section",
               "--topology", "grounded-cpw", "--width-mm", "1.5", "--height-mm", "1.53",
               "--gap-mm", "0.3", "--er", "4.5"]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(completed.stdout)
    assert payload["result"]["single_ended_z0_ohm"] == pytest.approx(50.9420598768, rel=1e-8)
    assert "board" not in payload
