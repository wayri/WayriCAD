"""Small standalone solver capability probe; never builds a scientific model.

Run with the selected solver interpreter and isolation enabled::

    python -I -X utf8 /path/to/solver_probe.py

The controller owns process timeout, cancellation and user-choice policy. A
passing probe establishes tiny complex-system execution, not runtime/model
qualification or a performance guarantee.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys


RESIDUAL_LIMIT = 1e-10


def _diagnostic(error):
    """Keep exception diagnostics useful and bounded for the UI protocol."""
    return (type(error).__name__ + ': ' + str(error))[:1200]


def _checked_solution(np, matrix, rhs, expected, actual):
    actual = np.asarray(actual).reshape(-1)
    if actual.shape != expected.shape or not np.all(np.isfinite(actual)):
        raise ValueError('Solver returned an invalid complex solution')
    residual = float(np.linalg.norm(matrix @ actual-rhs)/np.linalg.norm(rhs))
    error = float(np.linalg.norm(actual-expected)/np.linalg.norm(expected))
    if residual > RESIDUAL_LIMIT or error > RESIDUAL_LIMIT:
        raise ValueError(f'Tiny complex solve failed: residual={residual:.3g}, solution error={error:.3g}')
    return dict(available=True, relative_residual=residual,
                relative_solution_error=error, message='Tiny complex solve passed')


def _local_mkl_path():
    """Avoid upstream's recursive DLL search and stale path-pickle cache."""
    override = os.environ.get('EMERGE_PARDISO_PATH')
    if override:
        return override
    prefix = Path(sys.prefix)
    if sys.platform == 'win32':
        candidates = [prefix/'Library'/'bin'/name for name in
                      ('mkl_rt.3.dll', 'mkl_rt.2.dll', 'mkl_rt.1.dll', 'mkl_rt.dll')]
    elif sys.platform == 'darwin':
        candidates = [prefix/'lib'/name for name in ('libmkl_rt.dylib', 'libmkl_rt.2.dylib')]
    else:
        candidates = [prefix/folder/name for folder in ('lib', 'lib64')
                      for name in ('libmkl_rt.so.2', 'libmkl_rt.so', 'libmkl_rt.so.1')]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    from ctypes.util import find_library
    library = find_library('mkl_rt')
    if library:
        return library
    raise ImportError('MKL runtime was not found in this interpreter; select SUPERLU or configure EMERGE_PARDISO_PATH')


def _probe_pardiso(np, matrix, rhs, expected):
    library = _local_mkl_path()
    previous = os.environ.get('EMERGE_PARDISO_PATH')
    handle = None
    directory_handle = None
    try:
        os.environ['EMERGE_PARDISO_PATH'] = library
        if sys.platform == 'win32' and Path(library).is_file() and hasattr(os, 'add_dll_directory'):
            directory_handle = os.add_dll_directory(str(Path(library).resolve().parent))
        from emerge._emerge.solve_interfaces.pardiso_interface import PardisoInterface
        handle = PardisoInterface(nthreads=2)
        for phase in ('symbolic', 'numeric'):
            code = getattr(handle, phase)(matrix)
            if code != 0:
                raise RuntimeError(f'PARDISO {phase} failed with code {code}')
        actual, code = handle.solve(matrix, rhs)
        if code != 0:
            raise RuntimeError(f'PARDISO solve failed with code {code}')
        result = _checked_solution(np, matrix, rhs, expected, actual)
        result.update(threads=2, library=library)
        return result
    finally:
        try:
            if handle is not None:
                handle.clear_memory()
        finally:
            try:
                if directory_handle is not None:
                    directory_handle.close()
            finally:
                if previous is None:
                    os.environ.pop('EMERGE_PARDISO_PATH', None)
                else:
                    os.environ['EMERGE_PARDISO_PATH'] = previous


def probe_runtime():
    """Return JSON-compatible capability evidence for this interpreter."""
    result = dict(schema=1, runtime={}, available=[], preferred=None, diagnostics={})
    try:
        version = importlib.metadata.version('emerge')
        result['runtime']['emerge'] = version
        match = re.match(r'^(\d+)', version)
        if not match or int(match.group(1)) < 3:
            raise RuntimeError('EMerge 3 or newer is required')
        import numpy as np
        from scipy.sparse import csc_matrix
        from scipy.sparse.linalg import spsolve
        # Symmetric complex, non-Hermitian and well conditioned. The known
        # solution checks complex support independently of the residual.
        matrix = csc_matrix(np.array([[4+1j, 1-.5j], [1-.5j, 3+2j]], dtype=np.complex128))
        expected = np.array([1+2j, -.5+.25j], dtype=np.complex128)
        rhs = matrix @ expected
    except Exception as error:
        result['diagnostics']['runtime'] = dict(available=False, message=_diagnostic(error))
        return result
    try:
        result['diagnostics']['SUPERLU'] = _checked_solution(np, matrix, rhs, expected, spsolve(matrix, rhs))
        result['available'].append('SUPERLU')
    except Exception as error:
        result['diagnostics']['SUPERLU'] = dict(available=False, message=_diagnostic(error))
    try:
        result['diagnostics']['PARDISO'] = _probe_pardiso(np, matrix, rhs, expected)
        result['available'].append('PARDISO')
    except Exception as error:
        result['diagnostics']['PARDISO'] = dict(available=False, message=_diagnostic(error))
    result['preferred'] = 'PARDISO' if 'PARDISO' in result['available'] else ('SUPERLU' if 'SUPERLU' in result['available'] else None)
    return result


@contextmanager
def _quiet_output():
    """Keep imports/native library chatter out of the single-JSON protocol."""
    saved = []
    with open(os.devnull, 'w', encoding='utf-8') as sink:
        try:
            for descriptor in (1, 2):
                duplicate = os.dup(descriptor)
                saved.append((descriptor, duplicate))
                os.dup2(sink.fileno(), descriptor)
            with redirect_stdout(sink), redirect_stderr(sink):
                yield
        finally:
            for descriptor, duplicate in reversed(saved):
                os.dup2(duplicate, descriptor)
                os.close(duplicate)


def main():
    sys.dont_write_bytecode = True
    try:
        with _quiet_output():
            result = probe_runtime()
    except Exception as error:
        result = dict(schema=1, runtime={}, available=[], preferred=None,
                      diagnostics={'runtime':dict(available=False, message=_diagnostic(error))})
    print(json.dumps(result, allow_nan=False, separators=(',', ':')), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
