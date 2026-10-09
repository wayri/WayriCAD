"""One offline transaction at a time; results are consumed by the GUI thread."""
from dataclasses import dataclass
from queue import Empty, Queue
import threading


@dataclass(frozen=True)
class ApplyResult:
    backup: object = None
    error: BaseException = None


class ApplyWorker:
    def __init__(self, operation):
        self._operation = operation
        self._results = Queue()
        self._lock = threading.Lock()
        self._busy = False
        self._applied = False

    @property
    def busy(self):
        with self._lock:
            return self._busy

    def start(self):
        with self._lock:
            if self._busy or self._applied:
                return False
            self._busy = True
        # Normal interpreter shutdown must wait for transaction writes/rollback.
        thread = threading.Thread(target=self._run, daemon=False)
        try:
            thread.start()
        except BaseException:
            with self._lock:
                self._busy = False
            raise
        return True

    def _run(self):
        try:
            result = ApplyResult(backup=self._operation())
        except BaseException as error:
            result = ApplyResult(error=error)
        self._results.put(result)

    def poll(self):
        try:
            result = self._results.get_nowait()
        except Empty:
            return None
        with self._lock:
            self._busy = False
            self._applied = result.error is None
        return result
