import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from quick_pi_plugin.plane_ports_ui import launch_from_board


def frame(path):
    return SimpleNamespace(_busy=False,_snapshot_current=lambda:True,
        model_dimension=Mock(GetSelection=lambda:0),_series_request=None,_extra_sinks=[],
        board_path=str(path),_origin_sha=lambda:hashlib.sha256(b'board').hexdigest(),
        inventory={},_input_revision=0,_job=Mock())


def test_changed_source_during_modal_cannot_be_accepted_as_a_new_snapshot():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'board.kicad_pcb';path.write_bytes(b'board');owner=frame(path)
        def configure(parent):
            path.write_bytes(b'new board')
            return {},'GND'
        with patch('quick_pi_plugin.plane_ports_ui.configure',side_effect=configure):
            with pytest.raises(ValueError,match='changed during'):
                launch_from_board(owner)
        owner._job.assert_not_called()


def test_explicit_3d_mode_is_rejected_before_configuration_or_extraction():
    owner=SimpleNamespace(_busy=False,_snapshot_current=lambda:True,
                          model_dimension=Mock(GetSelection=lambda:1))
    with patch('quick_pi_plugin.plane_ports_ui.configure') as configure:
        with pytest.raises(ValueError,match='2.5D'):
            launch_from_board(owner)
        configure.assert_not_called()


def test_extraction_must_match_reviewed_snapshot_not_just_the_current_filename():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'board.kicad_pcb';path.write_bytes(b'board');owner=frame(path)
        owner._request=Mock(return_value={'action':'mesh'})
        owner._unit_ids=lambda role:[role]
        owner._task=Mock()
        with patch('quick_pi_plugin.plane_ports_ui.configure',return_value=({},'GND')):
            launch_from_board(owner)
        callback=owner._job.call_args.args[1]
        with pytest.raises(ValueError,match='does not match'):
            callback({'geometry':{'source_sha256':'wrong'},'mesh':{}})
        owner._task.assert_not_called()
