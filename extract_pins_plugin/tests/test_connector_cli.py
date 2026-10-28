"""CLI commands preserve pin identity, physical arrangement and source files."""
import json
from pathlib import Path

from extract_pins_plugin import cli, connector_cli


def test_labels_boardless_explicit_and_selected(tmp_path, capsys):
    source = tmp_path/'pins.csv'
    source.write_text('Pin,Name\n1,SCL\nA3,GND\n', encoding='utf-8')
    assert cli.main(['labels',str(source),'--columns','pin-label','--header','--select','A3','--prefix','CARD_','--format','json']) == 0
    rows=json.loads(capsys.readouterr().out)
    assert [(row['pin'],row['label']) for row in rows]==[('A3','CARD_GND')]
    assert source.read_text()=='Pin,Name\n1,SCL\nA3,GND\n'


def test_label_numbering_and_clipboard_kind(tmp_path,capsys):
    source=tmp_path/'names.txt';source.write_text('SCL\nSDA\nGND\n3V3\n')
    assert cli.main(['labels',str(source),'--columns','labels','--sequence','odd-even','--format','json'])==0
    assert [r['pin'] for r in json.loads(capsys.readouterr().out)]==['1','3','2','4']
    assert cli.main(['labels',str(source),'--kind','hierarchical','--select','2'])==0
    clip=capsys.readouterr().out
    assert '(hierarchical_label "SDA"' in clip
    assert clip.count('(uuid ')==1


def test_labels_invalid_selection_and_write_guards(tmp_path,capsys):
    source=tmp_path/'pins.csv';source.write_text('1,SCL\n')
    assert cli.main(['labels',str(source),'--select','9'])==2
    assert 'not found' in capsys.readouterr().err
    for destination in (source,tmp_path/'board.kicad_pcb',tmp_path/'board.kicad_sch'):
        assert cli.main(['labels',str(source),'--output',str(destination)])==2
        assert source.read_text()=='1,SCL\n'
    destination=tmp_path/'labels.txt'
    assert cli.main(['labels',str(source),'--output',str(destination)])==0
    before=destination.read_bytes()
    assert cli.main(['labels',str(source),'--output',str(destination)])==2
    assert destination.read_bytes()==before


def test_mate_json_and_paired_clipboard(tmp_path,capsys):
    source=tmp_path/'mate.json'
    source.write_text(json.dumps({
        'a':[dict(pin='1',label='SCL',x_mm=-1,y_mm=0),dict(pin='2',label='GND',x_mm=1,y_mm=0)],
        'b':[dict(pin='1',label='',x_mm=-1,y_mm=0),dict(pin='2',label='',x_mm=1,y_mm=0)],
        'pose_b':{'side':'bottom','mirror':False}}))
    assert cli.main(['connector-mate',str(source)])==0
    result=json.loads(capsys.readouterr().out)
    assert [(p['a']['pin'],p['b']['pin']) for p in result['pairs']]==[('1','2'),('2','1')]
    assert result['pairs'][0]['b_label']=='SCL'
    assert cli.main(['connector-mate',str(source),'--format','clipboard-pair'])==0
    text=capsys.readouterr().out
    assert text.count('(global_label ')==4
    assert text.count('(uuid ')==4
    assert '(at 60 ' in text


def test_partial_mating_preserves_diagnostics_and_requires_opt_in(tmp_path,capsys):
    source=tmp_path/'mate.json'
    source.write_text(json.dumps({'a':[dict(pin='1',label='SCL',x_mm=0,y_mm=0),dict(pin='2',label='GND',x_mm=2,y_mm=0)],
                                 'b':[dict(pin='X',label='',x_mm=0,y_mm=0)],
                                 'pose_b':{'x_mm':-1}}))
    assert cli.main(['connector-mate',str(source)])==3
    review=json.loads(capsys.readouterr().out)
    assert len(review['pairs'])==1 and len(review['unmatched_a'])==1
    assert cli.main(['connector-mate',str(source),'--format','clipboard-b'])==2
    assert 'Unmatched' in capsys.readouterr().err
    assert cli.main(['connector-mate',str(source),'--format','clipboard-b','--allow-partial'])==3
    assert '(global_label "SCL"' in capsys.readouterr().out


def test_physical_grid_uses_geometry_without_sorting_numbers(monkeypatch,tmp_path,capsys):
    class Footprint:
        def GetReference(self):return 'J2'
    class Board:
        def GetFootprints(self):return [Footprint()]
    monkeypatch.setattr(cli,'load_board',lambda path:Board())
    monkeypatch.setattr(connector_cli,'footprint_pins',lambda fp:[
        dict(pin='3',label='C',x_mm=0,y_mm=0),dict(pin='1',label='A',x_mm=1,y_mm=0),
        dict(pin='4',label='D',x_mm=0,y_mm=1),dict(pin='2',label='B',x_mm=1,y_mm=1)])
    assert cli.main(['connector-grid',str(tmp_path/'board.kicad_pcb'),'--ref','J2','--format','json'])==0
    grid=json.loads(capsys.readouterr().out)
    assert [[p['pin'] for p in row] for row in grid]==[['3','1'],['4','2']]
    assert cli.main(['connector-grid','unused','--ref','J2','--transpose','--format','json'])==0
    assert [[p['pin'] for p in row] for row in json.loads(capsys.readouterr().out)]==[['3','4'],['1','2']]
    assert cli.main(['connector-grid','unused','--ref','J9'])==2
