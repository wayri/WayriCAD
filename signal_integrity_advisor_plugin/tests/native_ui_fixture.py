"""Prepare saved native geometry before creating the standalone wx application."""
import copy
from functools import lru_cache
from pathlib import Path
import tempfile


@lru_cache(maxsize=1)
def board_fixture():
    """Initialize KiCad file I/O before wx.App, then retain the synthetic bytes.

    KiCad 10 on Windows can hang during standalone wx shutdown when its first
    board read/write happens after wx.App construction. UI tests follow the
    saved-board launcher's lifetime and copy this fixture for each test.
    """
    import pcbnew
    from .test_study_native import make_board

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'example.kicad_pcb'
        config = make_board(path)
        board = pcbnew.LoadBoard(str(path))
        if board is None:
            raise RuntimeError('KiCad could not load the synthetic UI fixture.')
        project = path.with_suffix('.kicad_pro')
        return path.read_bytes(), project.read_bytes() if project.is_file() else None, config


def copy_board_fixture(path):
    """Give each UI test its own saved PCB, project and editable study inputs."""
    board_bytes, project_bytes, config = board_fixture()
    path.write_bytes(board_bytes)
    if project_bytes is not None:
        path.with_suffix('.kicad_pro').write_bytes(project_bytes)
    return copy.deepcopy(config)
