"""Contain read-only analysis workers and their native conversion children."""
import os
import signal
import subprocess

_conversion_job = None


def worker_options():
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            **({'start_new_session': True} if os.name != 'nt' else {})}


def stop_worker(process):
    """Stop only the process/session created with worker_options, then reap it."""
    if os.name != 'nt':
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait(timeout=5)
    finally:
        if os.name != 'nt':
            # A converter can outlive a worker that handled TERM first.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def contain_converters():
    """Windows closes this job on worker death, killing converter descendants.

    No inheritable job handle is given to children. Assignment occurs BEFORE
    any converter launch, so abrupt worker termination cannot orphan its CLI.
    POSIX workers are contained by their parent's dedicated process session.
    """
    global _conversion_job
    if os.name != 'nt' or _conversion_job is not None:
        return
    import ctypes as c
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [('PerProcessUserTimeLimit', c.c_longlong), ('PerJobUserTimeLimit', c.c_longlong),
                    ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', c.c_size_t),
                    ('MaximumWorkingSetSize', c.c_size_t), ('ActiveProcessLimit', w.DWORD),
                    ('Affinity', c.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]

    class IO(c.Structure):
        _fields_ = [(name, c.c_ulonglong) for name in
                    ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                     'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class Extended(c.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO),
                    ('ProcessMemoryLimit', c.c_size_t), ('JobMemoryLimit', c.c_size_t),
                    ('PeakProcessMemoryUsed', c.c_size_t), ('PeakJobMemoryUsed', c.c_size_t)]

    api = c.WinDLL('kernel32', use_last_error=True)
    api.CreateJobObjectW.argtypes = (c.c_void_p, w.LPCWSTR)
    api.CreateJobObjectW.restype = w.HANDLE
    api.SetInformationJobObject.argtypes = (w.HANDLE, c.c_int, c.c_void_p, w.DWORD)
    api.SetInformationJobObject.restype = w.BOOL
    api.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
    api.AssignProcessToJobObject.restype = w.BOOL
    api.GetCurrentProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = (w.HANDLE,)
    handle = api.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(c.get_last_error(), 'Cannot create native analysis process containment')
    limits = Extended()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not api.SetInformationJobObject(handle, 9, c.byref(limits), c.sizeof(limits)) or
            not api.AssignProcessToJobObject(handle, api.GetCurrentProcess())):
        error = c.get_last_error()
        api.CloseHandle(handle)
        raise OSError(error, 'Cannot contain the native converter; analysis was not started')
    # Intentionally process-owned: explicit close here would terminate us.
    _conversion_job = handle
