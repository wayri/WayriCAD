"""A queued first-board read must not outlive a closed Quick PI window."""

from types import SimpleNamespace

import pytest

pytest.importorskip('wx')
pytest.importorskip('matplotlib')
from quick_pi_plugin.ui import QuickPIFrame


def test_deferred_inspection_and_job_ignore_closed_window():
    closed = SimpleNamespace(_closed=True, _closing=False)
    QuickPIFrame._inspect(closed)
    QuickPIFrame._job(closed, {'action': 'inspect'}, lambda value: value, 'Reading board')


def test_analysis_request_accepts_finite_inputs_and_rejects_nan():
    def control(value):
        return SimpleNamespace(GetValue=lambda: value)

    selection = SimpleNamespace(GetSelection=lambda: 0)
    sink = SimpleNamespace(GetSelection=lambda: 1)
    frame = SimpleNamespace(
        board_path='C:/Projects/Example/board.kicad_pcb',
        net=control('VCC'), edge=control('0.5'), plating=control('0.025'),
        source=selection, sink=sink, voltage=control('12'), current=control('1'),
        temperature=control('20'), ambient=control('20'), limit=control('150'),
        pulse=control('1'), load_mode=selection, model_dimension=selection,
        source_current_limit=control(''),sink_min_voltage=control(''),sink_max_voltage=control(''),
        _series_request=None,_extra_sinks=[],
        _terminals=[{'id': 'R1.1'}, {'id': 'J1.1'}],
    )
    request = QuickPIFrame._request(frame, 'solve')
    assert request['sinks'] == [{'terminal':'J1.1','current_A':1}]
    assert request['source_terminal'] == 'R1.1'
    frame.current = control('nan')
    with pytest.raises(ValueError, match='finite'):
        QuickPIFrame._request(frame, 'solve')


def test_3d_request_ignores_inactive_2d_screening_fields():
    def control(value):
        return SimpleNamespace(GetValue=lambda: value)

    frame = SimpleNamespace(
        board_path='C:/Projects/Example/board.kicad_pcb',
        net=control('VCC'), edge=control('0.5'), plating=control('0.025'),
        source=SimpleNamespace(GetSelection=lambda: 0),
        sink=SimpleNamespace(GetSelection=lambda: 1),
        voltage=control('12'), current=control('1'),
        temperature=control('20'), ambient=control('not applicable'),
        limit=control('not applicable'), pulse=control('not applicable'),
        load_mode=SimpleNamespace(GetSelection=lambda: 0),
        model_dimension=SimpleNamespace(GetSelection=lambda: 1),
        source_current_limit=control(''),sink_min_voltage=control(''),sink_max_voltage=control(''),
        _series_request=None,_extra_sinks=[],
        _terminals=[{'id': 'R1.1'}, {'id': 'J1.1'}],
    )
    request = QuickPIFrame._request(frame, 'solve')
    assert request['options'] == {'temperature_c': 20.}
