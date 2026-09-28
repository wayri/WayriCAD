"""The new CLI modes must reach the worker with explicit, bounded inputs."""
import json
from pathlib import Path

import pytest

from quick_pi_plugin import cli
from quick_pi_plugin import service
from quick_pi_plugin.report import write_diagnostic_report, write_sweep_report


@pytest.fixture
def board(tmp_path):
    path = tmp_path / "sample.kicad_pcb"
    path.write_text("(kicad_pcb)", encoding="utf-8")
    return path


@pytest.mark.parametrize("extra,action,expected", [
    (["--quick-therm", "air", "--power-field", "P", "--theta-ja-field", "RJA", "--thermal-refs", "U1"], "quick_therm", "air"),
    (["--quick-therm", "vacuum", "--power-field", "P", "--theta-jb-field", "RJB", "--board-rtheta", "8"], "quick_therm", "vacuum"),
    (["--return-path", "--net", "VIN", "--return-nets", "GND"], "return_path", "VIN"),
    (["--net", "VIN", "--source", "J1.1", "--sink", "U1.1", "--load-ohms", "10"], "solve", 10.),
    (["--net", "VIN", "--source", "J1.1", "--sink", "U1.1", "--sweep", "0.1", "2", "5"], "sweep", 5),
])
def test_cli_dispatch(monkeypatch, board, capsys, extra, action, expected):
    sent = []
    monkeypatch.setattr(service, "run_job", lambda request, timeout: sent.append(request) or {"ok": True})
    assert cli.main([str(board), *extra]) == 0
    request = sent[-1]
    assert request["action"] == action
    value = (request.get("environment") if action == "quick_therm" else
             request.get("signal_net") if action == "return_path" else
             request.get("load_resistance_ohm") if action == "solve" else request["sweep"]["points"])
    assert value == expected
    assert json.loads(capsys.readouterr().out)["ok"]


def test_cli_rejects_ambiguous_modes(monkeypatch, board, capsys):
    monkeypatch.setattr(service, "run_job", lambda *a, **k: pytest.fail("worker must not start"))
    assert cli.main([str(board), "--return-path", "--quick-therm", "air"]) == 2
    assert "Choose one" in capsys.readouterr().out


def test_cli_virtual_heatsink_mapping(monkeypatch, board, tmp_path):
    path = tmp_path / 'sinks.json'
    path.write_text(json.dumps({'U1': {'shape': 'resistance_only', 'contact_k_per_w': .2,
        'theta_sa_air_k_per_w': 8.}}), encoding='utf-8')
    sent = []
    monkeypatch.setattr(service, 'run_job', lambda request, timeout: sent.append(request) or {'ok': True})
    assert cli.main([str(board), '--quick-therm', 'air', '--power-field', 'P',
        '--theta-jc-field', 'RJC', '--thermal-refs', 'U1', '--heatsinks', str(path)]) == 0
    assert sent[-1]['heatsinks']['U1']['shape'] == 'resistance_only'
    assert sent[-1]['field_map']['theta_jc_k_per_w'] == 'RJC'


def test_standalone_sweep_and_thermal_reports(tmp_path):
    sweep = {"sweep": {"rows": [
        {"current_A": 1., "path_drop_V": .2, "sink_voltage_V": 4.8, "negative_sink_voltage": False},
        {"current_A": 2., "path_drop_V": .4, "sink_voltage_V": 4.6, "negative_sink_voltage": False},
    ]}}
    output = write_sweep_report(tmp_path / "sweep.html", sweep)
    assert "<svg" in Path(output["html"]).read_text(encoding="utf-8")
    assert json.loads(Path(output["json"]).read_text(encoding="utf-8"))["sweep"]["rows"][1]["current_A"] == 2.
    thermal = {"quick_therm": {"model": "steady-state lumped thermal screen", "environment": "air",
        "ambient_c": 20., "coverage": {"solved": 1, "scoped": 1, "excluded": []},
        "components": [{"reference": "U1", "power_w": 1., "resistance_k_per_w": 10., "junction_c": 30.,
            "heat_path": "heatsink", "heatsink": {"shape": "resistance_only", "width_mm": None}}],
        "assumptions": ["Mapped field"]}}
    output = write_diagnostic_report(tmp_path / "thermal.html", thermal)
    assert "U1" in Path(output["html"]).read_text(encoding="utf-8")
    assert "resistance only" in Path(output["html"]).read_text(encoding="utf-8")
    review = {"return_path": {"basis": "Sampled saved-board geometry", "warning_count": 1,
        "unknown_count": 0, "findings": [{"level": "warning", "code": "REFERENCE_GAP_SAMPLED",
            "layer": "F.Cu", "position_mm": [1., 2.], "detail": "Reference gap"}]}}
    output = write_diagnostic_report(tmp_path / "return.html", review)
    assert "REFERENCE_GAP_SAMPLED" in Path(output["html"]).read_text(encoding="utf-8")
