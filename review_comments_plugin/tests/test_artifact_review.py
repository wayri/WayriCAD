import base64
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from review_comments_plugin.bom_review import load_bom, bom_anchor
from review_comments_plugin.canvas_model import markers_from_rows
from review_comments_plugin.model import markdown, note, read_markers, project_markers
from review_comments_plugin.project_artifacts import discover_gerbers, read_artifact, gerber_anchor
from review_comments_plugin.review_targets import CONTEXT_MARKER, verify_target, visible_body
from review_comments_plugin.web_documents import ReviewDocuments

SCOPE = dict(repository='example/board', ref='a'*40, file='board.kicad_pcb')
BOARD = '(kicad_pcb (version 20260206) (footprint "R_0603" (uuid "part-one") (property "Reference" "R1") (property "Value" "10k") (property "MPN" "EXAMPLE")))'
GERBER = 'G04 Public test*\n%FSLAX46Y46*%\n%MOMM*%\n%ADD10C,0.5*%\nD10*\nX1000000Y2000000D03*\nM02*\n'


@pytest.fixture
def project(tmp_path):
    (tmp_path/'board.kicad_pcb').write_text(BOARD)
    (tmp_path/'fab').mkdir()
    (tmp_path/'fab/top.gbr').write_bytes(GERBER.encode())
    return tmp_path


def test_bom_cell_context_roundtrips_without_changing_online_v1_anchor(project):
    snapshot = load_bom(project/'board.kicad_pcb', root=project)
    target = bom_anchor(SCOPE, snapshot['rows'][0], snapshot['source_hashes'], field='MPN', variant='*')
    value = note('Check supplier field', target)
    body = markdown(value)
    decoded = read_markers(body, SCOPE)
    assert decoded == [value]
    assert visible_body(body) == 'Check supplier field'
    legacy = json.loads(base64.urlsafe_b64decode(body.split('kicad-review:v1 ')[1].split(' -->')[0] + '==='))
    assert 'context' not in legacy['anchor'] and legacy['anchor']['file'].endswith('.kicad_pcb')
    verify_target(decoded[0]['anchor'], project)
    (project/'board.kicad_pcb').write_text(BOARD.replace('(property "MPN" "EXAMPLE")', ''))
    with pytest.raises(ValueError, match='changed|no longer'):
        verify_target(target, project)


def test_duplicate_or_spliced_context_is_not_accepted(project):
    target = gerber_anchor(SCOPE, project, project/'fab/top.gbr', position=dict(x=1, y=2))
    body = markdown(note('Inspect this flash', target))
    extension = CONTEXT_MARKER.search(body)[0]
    assert 'context' not in read_markers(body+'\n'+extension, SCOPE)[0]['anchor']
    other = markdown(note('Different annotation', dict(SCOPE, kind='object', uuid='part-one')))
    assert 'context' not in read_markers(other+'\n'+extension, SCOPE)[0]['anchor']
    assert project_markers(body, dict(SCOPE, ref='b'*40))[0]['anchor']['context'] == target['context']
    assert read_markers(body, dict(SCOPE, ref='b'*40)) == []


def test_gerber_view_and_markers_are_bound_to_project_bytes_and_variant(project, tmp_path):
    documents = ReviewDocuments(project/'board.kicad_pcb')
    identifier = documents.add_gerber(project/'fab/top.gbr')
    payload = documents.load(identifier)
    assert payload['view'] == 'manufacturing' and payload['source'] == GERBER
    assert [path.name for path in discover_gerbers(project)] == ['top.gbr']
    target = gerber_anchor(SCOPE, project, project/'fab/top.gbr', variant='prototype', position=dict(x=1, y=2))
    value = note('Check aperture', target)
    rows = [dict(id='12', body=markdown(value), annotations=[value])]
    assert markers_from_rows(rows, SCOPE, 'synced')[0] == []
    artifact = dict(type='gerber', file='fab/top.gbr', sha256=payload['source_sha256'])
    markers, _ = markers_from_rows(rows, SCOPE, 'synced', artifact=artifact, variant='prototype')
    assert len(markers) == 1 and (markers[0].x, markers[0].y) == (1, 2)
    assert markers_from_rows(rows, SCOPE, 'synced', artifact=artifact, variant='production')[0] == []
    assert markers_from_rows(rows, SCOPE, 'synced', artifact=dict(artifact, sha256='0'*64))[0] == []
    assert markers_from_rows(rows, SCOPE, 'offline / stale', artifact=artifact)[0] == []
    outside = project.parent/'outside.gbr'
    outside.write_text(GERBER)
    with pytest.raises(ValueError, match='inside'):
        documents.add_gerber(outside)
    with pytest.raises(ValueError):
        read_artifact(project, project/'../outside.gbr')
    (project/'fab/top.gbr').write_text(GERBER+'G04 changed*')
    with pytest.raises(ValueError, match='changed'):
        documents.assert_current(identifier, payload['source_sha256'])
    with pytest.raises(ValueError, match='changed'):
        verify_target(target, project)


def test_changed_and_removed_origin_stays_unpublishable_but_gets_status_diagnostics(project):
    from review_comments_plugin.context_sync import parse_status_events
    from review_comments_plugin.session import ReviewSession
    def git(*args):
        return subprocess.run(['git', *args], cwd=project, check=True, capture_output=True).stdout.decode().strip()
    git('init', '-q')
    git('-c', 'user.name=Acceptance', '-c', 'user.email=acceptance@example.invalid', 'add', 'board.kicad_pcb')
    git('-c', 'user.name=Acceptance', '-c', 'user.email=acceptance@example.invalid', 'commit', '-qm', 'Test fixture')
    target = dict(SCOPE, ref=git('rev-parse', 'HEAD'), uuid='part-one', kind='object')
    class MemoryProvider:
        kind, number, provider = 'issue', 1, 'github'
        web_url = 'https://github.com/example/board/issues/1'
        def __init__(self):
            self.scope = SCOPE
            self.rows = [dict(id='2', body=markdown(note('Original review', target)), author='reviewer', updatedAt='now', root=False)]
            self.writes = []
        def snapshot(self): return [dict(row) for row in self.rows]
        def publish(self, body):
            self.writes.append(body)
            self.rows.append(dict(id=str(10+len(self.writes)), body=body, author='reviewer', updatedAt='now', root=False))
            return self.rows[-1]['id']
    provider = MemoryProvider()
    session = ReviewSession(dict(target, root=str(project), number=1), provider=provider, cache_dir=project/'cache', context_updates=True)
    session.refresh()
    session.draft('Keep this draft', target)
    (project/'board.kicad_pcb').write_text('(kicad_pcb (version 20260206))')
    for _ in range(2):
        with pytest.raises(ValueError, match='changed'):
            session.refresh()
    assert len(provider.writes) == 1
    assert parse_status_events(provider.rows, target)[0]['status'] == 'orphan'
    assert session.rows[0]['contextStatus'][0]['status'] == 'orphan'
    assert session.status != 'synced' and session.rows[0]['anchors'] == []
    assert session.draft()['text'] == 'Keep this draft'
    with pytest.raises(ValueError, match='Refresh'):
        session.publish('Must not send', target)


def test_generation_uses_disposable_inputs_and_preserves_existing_project_preferences(project, monkeypatch):
    from types import SimpleNamespace
    from review_comments_plugin import project_artifacts as artifacts
    board = project/'board.kicad_pcb'
    preferences = project/'board.kicad_prl'
    preferences.write_bytes(b'original preferences')
    original = board.read_bytes()
    def run(command, **options):
        copied = Path(command[-1])
        assert copied != board and copied.read_bytes() == original
        assert Path(options['cwd']) == copied.parent
        copied.with_suffix('.kicad_prl').write_bytes(b'CLI preferences')
        output = Path(command[command.index('--output')+1])
        (output/'top.gbr').write_bytes(GERBER.encode())
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
    monkeypatch.setattr(artifacts.subprocess, 'run', run)
    output, files = artifacts.generate_gerbers(board, cli='test-cli')
    assert len(files) == 1 and files[0].parent == output
    assert board.read_bytes() == original and preferences.read_bytes() == b'original preferences'
    assert not list(output.glob('.input-*'))


def test_generation_crash_is_actionable_and_never_overwrites_existing_cam(project, monkeypatch):
    from types import SimpleNamespace
    from review_comments_plugin import project_artifacts as artifacts
    monkeypatch.setattr(artifacts.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=3221225477, stdout=b'', stderr=b''))
    original = (project/'fab/top.gbr').read_bytes()
    with pytest.raises(ValueError, match='0xC0000005'):
        artifacts.generate_gerbers(project/'board.kicad_pcb', cli='test-cli')
    assert (project/'fab/top.gbr').read_bytes() == original
