"""Debounced, opt-in background checks for changes to analyzed nets."""

from threading import Thread


class NetChangeState:
    """Dispatch a new fingerprint once it agrees across two samples."""

    def __init__(self, baseline=None):
        self.baseline = baseline
        self.pending = None

    def observe(self, stamp):
        if self.baseline is None:
            self.baseline = stamp
        if stamp == self.baseline:
            self.pending = None
            return False
        if stamp != self.pending:
            self.pending = stamp
            return False
        self.baseline = stamp
        self.pending = None
        return True


class NetWatch:
    """Sample on a worker and deliver a settled change on the wx event loop."""

    def __init__(self, owner, read, ready, changed, failed, *, interval_ms=1600):
        import wx

        self._wx = wx
        self._read, self._ready = read, ready
        self._changed, self._failed = changed, failed
        self._interval = interval_ms
        self._timer = wx.Timer(owner)
        owner.Bind(wx.EVT_TIMER, self.poll, self._timer)
        self._epoch = 0
        self._state = None
        self._failures = 0
        self._closed = False
        self.running = False

    def arm(self, baseline=None):
        if self._closed:
            return
        self._epoch += 1
        self._state = NetChangeState(baseline)
        self._failures = 0
        self._timer.Start(self._interval)

    def disarm(self):
        self._epoch += 1
        self._timer.Stop()
        self._state = None

    def stop(self):
        self._closed = True
        self.disarm()

    def poll(self, event=None):
        if self._state is None or self.running or not self._ready():
            return
        self.running = True
        Thread(target=self._sample, args=(self._epoch,), daemon=True).start()

    def _sample(self, epoch):
        stamp, error = None, None
        try:
            stamp = self._read()
        except Exception as exc:
            error = exc
        if not self._closed:
            self._wx.CallAfter(self._complete, epoch, stamp, error)

    def _complete(self, epoch, stamp, error):
        self.running = False
        if epoch != self._epoch or self._state is None or not self._ready():
            return
        if error is not None:
            self._state.pending = None
            self._failures += 1
            if self._failures == 3:
                self._failed(error)
            return
        self._failures = 0
        if self._state.observe(stamp):
            self._changed(stamp)
