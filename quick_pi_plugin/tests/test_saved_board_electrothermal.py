"""Converted electrothermal models retain original project custody through solve."""
import hashlib
from unittest.mock import patch

import pytest

from quick_pi_plugin import electrothermal, electrothermal_service


@pytest.mark.parametrize('changed', [False, True])
def test_electrothermal_preserves_and_rechecks_conversion_provenance(tmp_path, changed):
    source=tmp_path/'board.kicad_pcb';source.write_bytes(b'saved PCB')
    project=source.with_suffix('.kicad_pro');project.write_bytes(b'{}')
    cli=tmp_path/'kicad-cli';cli.write_bytes(b'converter')
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    evidence=dict(source_path=str(source),source_fingerprints={str(source):sha(source),
        str(project):sha(project),str(source.with_suffix('.kicad_dru')):None},
        converter_path=str(cli),converter_sha256=sha(cli))
    prepared=dict(saved_board_provenance=evidence)
    def solve(model):
        if changed:project.write_bytes(b'{"changed":true}')
        return {'solved':True}
    with patch.object(electrothermal_service,'prepare_saved_study',return_value=prepared), \
         patch.object(electrothermal,'solve_electrothermal',side_effect=solve):
        request=dict(board_path=str(source),study={'electrical':{}})
        if changed:
            with pytest.raises(ValueError,match='changed'):electrothermal_service.execute(request)
        else:
            assert electrothermal_service.execute(request)['saved_board_provenance']==evidence
