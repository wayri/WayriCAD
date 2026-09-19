import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from wayricad_runtime import verification as v


def report(findings=None, unconnected=None):
    return {'$schema':'https://schemas.kicad.org/drc.v1.json','coordinate_units':'mm',
            'kicad_version':'10.0.5','source':'board.kicad_pcb',
            'included_severities':['error','warning'],'ignored_checks':[],
            'violations':findings or [],'unconnected_items':unconnected or [],'schematic_parity':[]}


def finding(severity='error'):
    return {'type':'clearance','description':'Clearance actual 0.10 mm', 'severity':severity,
            'items':[{'description':'Track [A] on F.Cu','pos':{'x':1.2,'y':2},'uuid':'one'},
                     {'description':'Pad 1 [B] of J1 on F.Cu','pos':{'x':1.4,'y':2},'uuid':'two'}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    board=tmp_path/'board.kicad_pcb';board.write_text('(kicad_pcb)')
    cli=tmp_path/'kicad-cli';cli.write_text('fake executable')
    monkeypatch.setattr(v,'discover_cli',lambda explicit:cli)
    return board,tmp_path/'drc.json'


def run_result(monkeypatch, document, code=0, mutate=None):
    def run(command, **options):
        assert '--save-board' not in command
        assert '--refill-zones' in command and '--exit-code-violations' in command
        if document is not None:
            Path(command[command.index('--output')+1]).write_text(json.dumps(document))
        if mutate:mutate()
        return SimpleNamespace(returncode=code,stderr='engine diagnostic',stdout='')
    monkeypatch.setattr(v.subprocess,'run',run)


def test_clean_native_report_and_hash(setup,monkeypatch):
    board,output=setup;run_result(monkeypatch,report())
    result=v.verify_board(board,output)
    assert result['accepted'] and result['clean']
    assert result['input_sha256']==v._digest(board)
    assert result['report_sha256']==v._digest(output)


def test_existing_violations_can_pass_regression_without_claiming_clean(setup,monkeypatch):
    board,output=setup;document=report([finding()]);run_result(monkeypatch,document,5)
    result=v.verify_board(board,output,baseline=document)
    assert result['accepted'] and not result['clean']
    assert result['counts']['errors']==1


def test_unconnected_blocks_acceptance(setup,monkeypatch):
    board,output=setup;run_result(monkeypatch,report(unconnected=[finding('warning')]),5)
    result=v.verify_board(board,output)
    assert not result['accepted'] and result['counts']['unconnected']==1


def test_identity_ignores_only_order_and_uuid():
    first=report([finding()]);second=copy.deepcopy(first)
    second['violations'][0]['items'].reverse()
    for item in second['violations'][0]['items']:item['uuid']='different'
    assert not v.compare_reports(first,second)['new']
    second['violations'][0]['items'][0]['pos']['x']+=.00001
    result=v.compare_reports(first,second)
    assert result['new_errors']==1 and not result['accepted'] and len(result['resolved'])==1


def test_changed_description_severity_and_duplicate_counts_are_not_hidden():
    first=report([finding('warning')]);second=report([finding(),finding()])
    result=v.compare_reports(first,second)
    assert result['new_errors']==2 and result['new'][0]['count']==2
    second['violations'][0]['description']='Clearance actual 0.09 mm'
    assert len(v.compare_reports(first,second)['new'])==2


@pytest.mark.parametrize('kind',['missing','badjson','engine','timeout','changed','contradictory'])
def test_failed_engine_never_reuses_old_report(setup,monkeypatch,kind):
    board,output=setup;output.write_text('old evidence')
    run_result(monkeypatch,None if kind=='missing' else report(), 2 if kind=='engine' else 5 if kind=='contradictory' else 0,
               mutate=(lambda:board.write_text('modified')) if kind=='changed' else None)
    if kind=='badjson':
        def invalid(command,**kwargs):
            Path(command[command.index('--output')+1]).write_text('{broken')
            return SimpleNamespace(returncode=0,stderr='')
        monkeypatch.setattr(v.subprocess,'run',invalid)
    if kind=='timeout':
        def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('kicad-cli',1)
        monkeypatch.setattr(v.subprocess,'run',timeout)
    with pytest.raises(v.VerificationError):v.verify_board(board,output)
    assert output.read_text()=='old evidence'


def test_bad_report_shape_and_configuration_change_rejected():
    with pytest.raises(v.VerificationError):v.parse_report({})
    second=report();second['ignored_checks']=[{'key':'clearance','description':'clearance'}]
    with pytest.raises(v.VerificationError,match='configuration'):v.compare_reports(report(),second)


def test_output_cannot_clobber_source_or_baseline(setup):
    board,output=setup
    with pytest.raises(v.VerificationError):v.verify_board(board,board)
    output.write_text(json.dumps(report()))
    with pytest.raises(v.VerificationError):v.verify_board(board,output,baseline=output)
