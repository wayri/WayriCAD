"""The CLI preserves complete data and rejects ambiguous source evidence."""
import hashlib
import json

from wayricad_runtime.pocket_kivi_cli import main


def inputs(tmp_path):
    board = tmp_path / 'example.kicad_pcb'
    board.write_bytes(b'(kicad_pcb)\n')
    digest = hashlib.sha256(board.read_bytes()).hexdigest()
    result = tmp_path / 'result.json'
    result.write_text(json.dumps({'source_sha256': digest, 'values': [1, None, 2]}))
    output = tmp_path / 'portable.json'
    args = [str(result), str(output), '--board', str(board), '--source-sha256', digest,
            '--tool', 'Test producer', '--version', '1.0', '--saved-source']
    return board, result, output, args


def test_complete_cli_export(tmp_path, capsys):
    board, result, output, args = inputs(tmp_path)
    original = result.read_bytes()
    assert main(args) == 0
    saved = json.loads(output.read_text())
    assert saved['values'] == [1, None, 2]
    assert saved['source_path'] == board.name
    assert result.read_bytes() == original
    assert capsys.readouterr().err == ''


def test_reject_stale_source(tmp_path):
    board, result, output, args = inputs(tmp_path)
    board.write_bytes(b'changed')
    assert main(args) == 2
    assert not output.exists()


def test_reject_duplicate_fields(tmp_path):
    board, result, output, args = inputs(tmp_path)
    result.write_text('{"values": [1], "values": [2]}')
    assert main(args) == 2
    assert not output.exists()


def test_reject_nonfinite(tmp_path):
    board, result, output, args = inputs(tmp_path)
    result.write_text('{"values": [NaN]}')
    assert main(args) == 2
    assert not output.exists()


def test_reject_overwrite(tmp_path):
    board, result, output, args = inputs(tmp_path)
    args[1] = str(result)
    original = result.read_bytes()
    assert main(args) == 2
    assert result.read_bytes() == original
