"""The IPC capture is private, revision bound and cleaned on every exit."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from wayricad_runtime import context
from wayricad_runtime.context import LaunchContext
from wayricad_runtime.live_pcb import capture_live_pcb
from wayricad_runtime.saved_board import _sha


def fixture(tmp_path, monkeypatch):
    saved = tmp_path / 'coupon.kicad_pcb'
    saved.write_bytes(b'saved board')
    saved.with_suffix('.kicad_pro').write_text('{}')
    saved.with_suffix('.kicad_dru').write_text('(version 1)')
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setenv('WAYRICAD_ANALYSIS_SCRATCH', str(scratch))
    origin = LaunchContext('fixture-socket', 'fixture-token')
    active = SimpleNamespace(name=str(saved))

    def connect(*, launch_context, timeout_ms):
        assert launch_context is origin
        return SimpleNamespace(get_board=lambda: active)

    active.get_as_string = lambda: '(kicad_pcb (version 20260206) (generator fixture))'
    monkeypatch.setattr(context, 'connect', connect)
    return saved, scratch, origin, active


def test_capture_uses_live_bytes_and_saved_external_rules(tmp_path, monkeypatch):
    saved, scratch, origin, active = fixture(tmp_path, monkeypatch)
    before = _sha(saved)
    with capture_live_pcb(saved, origin) as (snapshot, record):
        assert snapshot.read_text() == active.get_as_string()
        assert snapshot.with_suffix('.kicad_dru').read_text() == '(version 1)'
        assert record['snapshot_sha256'] == _sha(snapshot)
        assert record['origin_sha256'] == before
        assert record['project_source'] == 'saved project and custom rules'
    assert _sha(saved) == before and list(scratch.iterdir()) == []


def test_capture_rejects_wrong_document_and_saved_rules_change(tmp_path, monkeypatch):
    saved, scratch, origin, active = fixture(tmp_path, monkeypatch)
    other = tmp_path / 'same bytes.kicad_pcb'
    other.write_bytes(saved.read_bytes())
    active.name = str(other)
    with pytest.raises(ValueError, match='changed boards'):
        with capture_live_pcb(saved, origin):
            pytest.fail('wrong document accepted')
    active.name = str(saved)
    with pytest.raises(ValueError, match='changed during the live run'):
        with capture_live_pcb(saved, origin):
            saved.with_suffix('.kicad_dru').write_text('(version 2)')
    assert list(scratch.iterdir()) == []



def test_watched_capture_checks_routes_only_while_copying(tmp_path, monkeypatch):
    saved, _, origin, active = fixture(tmp_path, monkeypatch)
    from wayricad_runtime import live_pcb

    reads = []
    monkeypatch.setattr(live_pcb, '_route_digest',
                        lambda board, nets: reads.append((board, list(nets))) or 'captured-revision')
    with capture_live_pcb(saved, origin, watch_nets=['VDD', 'VDD']) as (_, record):
        assert record['route_stamp'] == 'captured-revision'
        assert record['route_nets'] == ['VDD']
        active.name = 'changed after copy'
    assert reads == [(active, ['VDD']), (active, ['VDD'])]


def test_watched_capture_rejects_changes_during_copy(tmp_path, monkeypatch):
    saved, scratch, origin, _ = fixture(tmp_path, monkeypatch)
    from wayricad_runtime import live_pcb

    revisions = iter(('before', 'after'))
    monkeypatch.setattr(live_pcb, '_route_digest', lambda board, nets: next(revisions))
    with pytest.raises(ValueError, match='Live routing changed during capture'):
        with capture_live_pcb(saved, origin, watch_nets=['VDD']):
            pytest.fail('An unstable edit was accepted')
    assert list(scratch.iterdir()) == []
