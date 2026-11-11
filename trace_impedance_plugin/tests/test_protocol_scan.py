from types import SimpleNamespace
from unittest.mock import patch

import pytest

from trace_impedance_plugin import bulk, cli
from trace_impedance_plugin.protocol_scan import scan_engine
from trace_impedance_plugin.protocol_validation import screen_protocols


def test_empty_unassigned_net_does_not_break_discovery():
    with patch.object(bulk,'available_nets',return_value=['','GND','RF_OUT']), \
         patch.object(bulk,'extract_board',return_value={'nets':[],'coverage':{'complete':True}}) as extract:
        result=scan_engine(object())
    assert extract.call_args.kwargs['nets']==['RF_OUT']
    assert result['discovery']['unclassified']==['GND']


def test_ambiguous_only_scan_does_not_construct_native_geometry():
    with patch.object(bulk,'available_nets',return_value=['USB_CLK']), \
         patch.object(bulk,'extract_board',side_effect=AssertionError('must not extract')):
        result=scan_engine(object())
    assert result['findings']
    assert all(row['status']=='needs_review' for row in result['findings'])


def test_net_budget_retains_omissions_and_marks_incomplete():
    with patch.object(bulk,'available_nets',return_value=['RF_2','RF_1']), \
         patch.object(bulk,'extract_board',return_value={'nets':[],'coverage':{'complete':True}}):
        result=scan_engine(object(),max_nets=1)
    assert result['status']=='incomplete'
    assert result['coverage']['omitted_protocol_nets']==['RF_2']


@pytest.mark.parametrize('targets',[[],['rf'],True,{'rf':'50'}])
def test_invalid_target_shape_is_actionable(targets):
    with pytest.raises(ValueError):
        screen_protocols({'profiles':[],'matches':[]},{},targets=targets)


def test_protocol_config_file_budget(tmp_path):
    path=tmp_path/'rules.json'
    path.write_bytes(b' '* (1024*1024+1))
    with pytest.raises(ValueError,match='1 MiB'):
        cli.read_protocol_json(path)


def test_html_escapes_untrusted_net_and_recommendations():
    from trace_impedance_plugin.protocol_ui import report_html
    html=report_html({'board_sha256':'abc','result':{'findings':[dict(
        net='<script>x</script>',profile_id='rf',status='unresolved',issues=[
            dict(code='X',message='<img src=x>',suggestion='a&b')])]}})
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '&lt;img' in html and 'a&amp;b' in html


@pytest.mark.parametrize('frequency',[0,-1,float('nan'),float('inf'),True])
def test_frequency_rejected_even_without_candidates(frequency):
    with pytest.raises(ValueError,match='frequency'):
        scan_engine(object(),frequency_mhz=frequency)


def test_worker_crash_is_controlled_and_source_is_unchanged(tmp_path,monkeypatch):
    from trace_impedance_plugin import protocol_ui
    source=tmp_path/'Example.kicad_pcb';source.write_text('board')
    process=SimpleNamespace(returncode=-1073741819,poll=lambda:-1073741819)
    monkeypatch.setattr(protocol_ui.subprocess,'Popen',lambda *a,**kw:process)
    with pytest.raises(RuntimeError,match='KiCad remains open'):
        protocol_ui.scan_saved(source,{},lambda:False)
    assert source.read_text()=='board'


def test_cancel_reaps_only_owned_worker(tmp_path,monkeypatch):
    from trace_impedance_plugin import protocol_ui
    from wayricad_runtime import analysis_process
    source=tmp_path/'Example.kicad_pcb';source.write_text('board')
    process=SimpleNamespace(returncode=None,poll=lambda:None)
    stopped=[]
    monkeypatch.setattr(protocol_ui.subprocess,'Popen',lambda *a,**kw:process)
    monkeypatch.setattr(analysis_process,'stop_worker',lambda child:stopped.append(child))
    with pytest.raises(InterruptedError,match='cancelled'):
        protocol_ui.scan_saved(source,{},lambda:True)
    assert stopped==[process]


def test_worker_result_rejected_if_source_changes(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from trace_impedance_plugin import protocol_ui
    source=tmp_path/'Example.kicad_pcb';source.write_text('board')
    def start(argv,**kwargs):
        Path(argv[-1]).write_text(json.dumps({'result':{}}))
        source.write_text('changed')
        return SimpleNamespace(returncode=0,poll=lambda:0)
    monkeypatch.setattr(protocol_ui.subprocess,'Popen',start)
    with pytest.raises(ValueError,match='changed'):
        protocol_ui.scan_saved(source,{},lambda:False)


@pytest.mark.parametrize('status,rows,expected',[
    ('screened',['within_screening_target'],0),
    ('screened',['outside_target'],2),
    ('screened',['unresolved'],3),
    ('screened',['needs_review'],3),
    ('screened',[],3),
    ('incomplete',['within_screening_target'],3),
])
def test_cli_protocol_exit_statuses(status,rows,expected,monkeypatch,capsys):
    monkeypatch.setattr(cli,'analyze',lambda args:{'result':dict(
        status=status,findings=[{'status':row} for row in rows])})
    assert cli.main(['protocols','Example.kicad_pcb'])==expected
    assert capsys.readouterr().out


def test_cli_never_overwrites_protocol_inputs(tmp_path,monkeypatch):
    config=tmp_path/'rules.json';config.write_text('[]')
    monkeypatch.setattr(cli,'analyze',lambda args:{'result':dict(status='screened',findings=[])})
    assert cli.main(['protocols','Example.kicad_pcb','--rules',str(config),'--output',str(config)])==1
    assert config.read_text()=='[]'


def test_protocol_report_pair_rolls_back_and_checks_all_source_files(tmp_path,monkeypatch):
    import json
    from trace_impedance_plugin.bulk_ui import source_fingerprints
    from trace_impedance_plugin.protocol_ui import export_report
    from wayricad_runtime import report_ui
    source=tmp_path/'Example.kicad_pcb';source.write_text('board')
    document=dict(board=str(source),board_sha256=source_fingerprints(source)[str(source)],
                  source_files=source_fingerprints(source),result=dict(schema='test',findings=[]))
    target=tmp_path/'screen.html';evidence=target.with_suffix('.json')
    export_report(target,document)
    assert json.loads(evidence.read_text())==document
    previous={target:target.read_bytes(),evidence:evidence.read_bytes()}
    replace=report_ui.os.replace;calls=[]
    def fail_second(src,dst):
        calls.append(dst)
        if len(calls)==2:raise OSError('simulated evidence publication failure')
        return replace(src,dst)
    with monkeypatch.context() as patcher:
        patcher.setattr(report_ui.os,'replace',fail_second)
        with pytest.raises(OSError,match='simulated'):
            export_report(target,document)
    assert all(path.read_bytes()==data for path,data in previous.items())
    source.with_suffix('.kicad_pro').write_text('{}')
    with pytest.raises(ValueError,match='changed'):
        export_report(target,document)
    assert all(path.read_bytes()==data for path,data in previous.items())
