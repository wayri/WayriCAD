"""Abrupt analysis-worker cancellation must not orphan its native converter."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

from wayricad_runtime.analysis_process import stop_worker, worker_options


def alive(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            # Linux zombies no longer execute or hold snapshot files.
            status = Path(f'/proc/{pid}/stat')
            return not (status.is_file() and status.read_text().split()[2] == 'Z')
        except ProcessLookupError:
            return False
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    api.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = api.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return api.WaitForSingleObject(handle, 0) == 258
    finally:
        api.CloseHandle(handle)


def test_worker_cancellation_kills_owned_converter_before_scratch_cleanup(tmp_path):
    child = tmp_path/'converter.py'
    child.write_text('import time\ntime.sleep(120)\n')
    worker = tmp_path/'worker.py'
    worker.write_text(
        'import sys,subprocess,time\nfrom pathlib import Path\n'
        f'sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r})\n'
        'from wayricad_runtime.analysis_process import contain_converters\n'
        'contain_converters()\n'
        f'p=subprocess.Popen([sys.executable,{str(child)!r}])\n'
        f'Path({str(tmp_path/"pid")!r}).write_text(str(p.pid))\n'
        'time.sleep(120)\n')
    process = subprocess.Popen([sys.executable, '-B', str(worker)], **worker_options())
    pid = None
    try:
        deadline = time.monotonic()+10
        while not (tmp_path/'pid').exists() and time.monotonic()<deadline:
            assert process.poll() is None, 'Worker containment failed before converter launch'
            time.sleep(.05)
        pid = int((tmp_path/'pid').read_text())
        assert alive(pid)
        stop_worker(process)
        deadline = time.monotonic()+5
        while alive(pid) and time.monotonic()<deadline:
            time.sleep(.05)
        assert not alive(pid), 'Converter survived analysis cancellation'
    finally:
        if process.poll() is None:
            stop_worker(process)
        if pid is not None and alive(pid):
            os.kill(pid, 9)  # Only the child created and identified above.
