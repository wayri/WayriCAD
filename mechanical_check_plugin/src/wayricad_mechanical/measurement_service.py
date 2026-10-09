"""Report-bound private geometry cache for background native UI measurements."""
import copy
from contextlib import contextmanager
import hashlib
import json
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from .proximity import envelope_measure
from .runtime import Cancelled, run_process


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _Cancellation:
    def __init__(self, closed, caller):
        self.closed, self.caller = closed, caller

    def is_set(self):
        return self.closed.is_set() or bool(self.caller and self.caller.is_set())


class MeasurementSession:
    """Own at most one run. Closing cancels workers before removing geometry.

    No FreeCAD imports in this process. Source checks occur before and after
    queries, including cache hits, so stale reports never produce live readings.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._temporary = None
        self._token = None
        self._sources = {}
        self._records = {}
        self._bodies = {}
        self._manifest = {}

    def bind(self, report, geometry_directory, runtime, sources):
        with self._operation():
            if self._closed.is_set():
                raise Cancelled('Measurement session closed')
            self._check_sources(sources)
            if self._temporary:
                self._temporary.cleanup()
            self._temporary = tempfile.TemporaryDirectory(prefix='wayricad-measure-')
            self._root = Path(self._temporary.name)
            self._manifest = {}
            if geometry_directory:
                shutil.copytree(geometry_directory, self._root / 'solids')
                self._manifest = json.loads((self._root / 'solids/manifest.json').read_text(encoding='utf-8'))
                for item in self._manifest.values():
                    item['sha256'] = fingerprint(self._root / 'solids' / item['file'])
            self._runtime = dict(runtime)
            self._sources = dict(sources)
            self._mode = report['rules']['mode']
            self._bodies = {b['ref']: {key: copy.deepcopy(b[key]) for key in ('ref', 'bounds', 'side', 'kind')}
                            for b in report['bodies']}
            self._records = {tuple(sorted(m['refs'])): copy.deepcopy(m) for m in report.get('proximity', [])}
            self._token = uuid.uuid4().hex
            report['_measurement_session'] = self._token

    @staticmethod
    def _check_sources(sources):
        for path, digest in sources.items():
            try:
                same = fingerprint(path) == digest
            except OSError:
                same = False
            if not same:
                raise RuntimeError('Analysis source changed or became unavailable; rerun Mechanical Check before measuring')

    def measure(self, report, first_ref, second_ref, cancel=None):
        if first_ref == second_ref:
            raise ValueError('Choose two different parts')
        with self._operation():
            cancellation = _Cancellation(self._closed, cancel)
            if cancellation.is_set():
                raise Cancelled('Measurement cancelled')
            key = tuple(sorted((first_ref, second_ref)))
            live = bool(self._token and report.get('_measurement_session') == self._token)
            if not live:
                # Imported reports retain already calculated evidence only.
                for record in report.get('measurements', []) + report.get('proximity', []):
                    if (record.get('type') != 'point_ruler' and tuple(sorted(record.get('refs', []))) == key
                            and record.get('status', 'measured') == 'measured'):
                        return copy.deepcopy(record)
                raise RuntimeError('Live query geometry is unavailable for this report. Run Mechanical Check again to measure this pair.')
            self._check_sources(self._sources)
            if key in self._records:
                result = self._records[key]
            elif self._mode == 'quick2d':
                try:
                    result = envelope_measure(self._bodies[first_ref], self._bodies[second_ref])
                except KeyError as exc:
                    raise ValueError('Selected part has no usable footprint envelope') from exc
            else:
                try:
                    entries = [self._manifest[ref] for ref in (first_ref, second_ref)]
                except KeyError as exc:
                    raise ValueError('Selected part has no cached solid geometry; review model coverage and rerun') from exc
                paths = [self._root / 'solids' / item['file'] for item in entries]
                self._check_sources({str(path): item['sha256'] for path, item in zip(paths, entries)})
                request = dict(refs=[first_ref, second_ref], files=[str(path) for path in paths],
                               evidence=[item['evidence'] for item in entries])
                request_path, result_path = self._root / 'query.json', self._root / 'answer.json'
                request_path.write_text(json.dumps(request), encoding='utf-8')
                result_path.unlink(missing_ok=True)
                run_process([self._runtime['freecad_python'], Path(__file__).with_name('worker_entry.py'),
                             'measurement_worker', request_path, result_path], self._root / 'query.log', cancellation, timeout=60)
                result = json.loads(result_path.read_text(encoding='utf-8'))
            if cancellation.is_set():
                raise Cancelled('Measurement cancelled')
            self._check_sources(self._sources)
            self._records[key] = copy.deepcopy(result)
            return copy.deepcopy(result)

    @contextmanager
    def _operation(self):
        with self._lock:
            try:
                yield
            finally:
                if self._closed.is_set():
                    self._cleanup()

    def _cleanup(self):
        if self._temporary:
            self._temporary.cleanup()
            self._temporary = None
        self._token = None
        self._records.clear()
        self._bodies.clear()

    def close(self):
        self._closed.set()
        # A background operation owns cleanup until its cancellable worker exits.
        # Closing/rerunning the UI must never wait on the kernel or source hashing.
        if self._lock.acquire(blocking=False):
            try:
                self._cleanup()
            finally:
                self._lock.release()
