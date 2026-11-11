"""Heavy solver runs must account for system paging, not only their D: output."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.run_paper_antenna_screening import check_operating_reserve, operating_volumes


def test_insufficient_system_volume_refuses_before_solve():
    def usage(volume):
        return SimpleNamespace(free=(7 if volume=='C:\\' else 180)*1024**3)
    with patch('tools.run_paper_antenna_screening.operating_volumes',return_value={'C:\\','D:\\'}), \
         patch('tools.run_paper_antenna_screening.shutil.disk_usage',side_effect=usage):
        with pytest.raises(RuntimeError,match='system/paging'):
            check_operating_reserve(Path('.'))


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows paging inventory')
def test_windows_paging_inventory_included():
    with patch('tools.run_paper_antenna_screening.subprocess.check_output',return_value='["C:\\\\pagefile.sys","E:\\\\pagefile.sys"]'):
        volumes=operating_volumes(Path('D:/Evidence/run'))
    assert {'C:\\','D:\\','E:\\'}<=volumes


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows paging inventory')
def test_unknown_paging_inventory_fails_closed():
    with patch('tools.run_paper_antenna_screening.subprocess.check_output',side_effect=OSError('unavailable')):
        with pytest.raises(RuntimeError,match='not started'):
            operating_volumes(Path('D:/Evidence/run'))
