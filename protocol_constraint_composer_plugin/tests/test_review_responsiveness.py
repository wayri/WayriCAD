"""Transaction lifecycle and bounded evidence views without a GUI event loop."""
import json
import subprocess
import sys
import threading
import time

import pytest

from protocol_constraint_composer_plugin.constraint_studio.apply_worker import ApplyWorker
from protocol_constraint_composer_plugin.constraint_studio.report_view import ReportPages, PAGE_SIZE, TEXT_LIMIT, report_excerpt
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace, apply_bundle


def result_of(worker):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        result=worker.poll()
        if result is not None:return result
        time.sleep(.001)
    pytest.fail('Worker did not publish a result')


def test_apply_is_background_single_flight_until_result_consumed():
    entered=threading.Event();release=threading.Event();done=threading.Event();threads=[]
    def operation():
        threads.append(threading.current_thread());entered.set()
        assert release.wait(3)
        done.set();return 'backup-location'
    worker=ApplyWorker(operation)
    try:
        assert worker.start() and entered.wait(2)
        assert worker.busy and not worker.start() and worker.poll() is None
        assert threads[0] is not threading.current_thread() and not threads[0].daemon
    finally:release.set()
    assert done.wait(2)
    assert worker.busy and not worker.start()  # GUI must consume completion first.
    result=result_of(worker)
    assert result.backup=='backup-location' and result.error is None
    assert not worker.busy and not worker.start() and worker.poll() is None


def test_apply_error_is_delivered_and_retry_is_allowed():
    calls=[];failure=OSError('Synthetic write failure')
    def operation():
        calls.append(1)
        if len(calls)==1:raise failure
        return None
    worker=ApplyWorker(operation)
    assert worker.start()
    assert result_of(worker).error is failure
    assert not worker.busy and worker.start()
    assert result_of(worker).error is None
    assert not worker.start() and len(calls)==2


def test_thread_start_failure_releases_single_flight(monkeypatch):
    worker=ApplyWorker(lambda:None)
    def fail(_):raise RuntimeError('Thread unavailable')
    monkeypatch.setattr(threading.Thread,'start',fail)
    with pytest.raises(RuntimeError,match='Thread unavailable'):worker.start()
    assert not worker.busy


def test_real_apply_worker_preserves_fingerprints_and_backups(project,tmp_path):
    original=project.with_suffix('.kicad_dru').read_bytes()
    workspace=Workspace.load(project);workspace.document.rules[0].name='Reviewed synthetic rule'
    folder=workspace.export_bundle(tmp_path/'review')
    assert project.with_suffix('.kicad_dru').read_bytes()==original
    worker=ApplyWorker(lambda:apply_bundle(folder,True))
    assert worker.start()
    result=result_of(worker)
    assert result.error is None
    assert (result.backup/project.with_suffix('.kicad_dru').name).read_bytes()==original
    assert b'Reviewed synthetic rule' in project.with_suffix('.kicad_dru').read_bytes()
    assert not worker.start()


def test_exported_helper_imports_without_source_checkout(project,tmp_path):
    folder=Workspace.load(project).export_bundle(tmp_path/'review')
    assert (folder/'_apply/constraint_studio/apply_worker.py').is_file()
    script="import sys; sys.path.insert(0,sys.argv[1]); from constraint_studio.offline_gui import main; from constraint_studio.apply_worker import ApplyWorker; print('helper-import-ok')"
    result=subprocess.run([sys.executable,'-I','-B','-c',script,str(folder/'_apply')],cwd=folder,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='helper-import-ok'


def test_large_report_paging_retains_every_record_and_crossprobe_id(monkeypatch):
    native={'violations':[{'severity':'error','type':'clearance','description':f'Violation {i}',
                           'items':[{'uuid':f'uuid-{i}'}]} for i in range(12003)]}
    original=json.dumps(native)
    pages=ReportPages.from_native(native)
    assert pages.count==12003 and pages.page_count==61
    seen=[]
    for page in range(pages.page_count):
        rows=pages.rows();assert len(rows)<=PAGE_SIZE
        seen.extend(row['uuids'][0] for row in rows)
        assert rows[0]['native_record'] is native['violations'][page*PAGE_SIZE]
        pages.move(1)
    assert seen==[f'uuid-{i}' for i in range(12003)]
    assert pages.page==60 and len(pages.rows())==3
    assert json.dumps(native)==original
    # Filtering uses the precomputed search index, including item UUIDs.
    monkeypatch.setattr('protocol_constraint_composer_plugin.constraint_studio.report_view.json.dumps',lambda *_:pytest.fail('Filter serialized native records'))
    pages.filter('UUID-12002')
    assert pages.page==0 and pages.count==1 and pages.rows()[0]['uuids']==['uuid-12002']
    pages.filter('absent-record');pages.move(20)
    assert pages.count==0 and pages.page==0 and pages.rows()==[]
    pages.filter('');pages.move(-100)
    assert pages.count==12003 and pages.page==0


@pytest.mark.parametrize('data',[{},[],{'violations':'invalid'}])
def test_invalid_report_stays_invalid(data):
    with pytest.raises(ValueError):ReportPages.from_native(data)


def test_report_text_is_bounded_without_changing_source():
    text='x'*(TEXT_LIMIT+5000)
    excerpt=report_excerpt(text,'original.json')
    assert excerpt.startswith(text[:TEXT_LIMIT]) and excerpt.endswith('original.json')
    assert len(excerpt)<TEXT_LIMIT+100 and len(text)==TEXT_LIMIT+5000
    assert report_excerpt('complete report')=='complete report'
