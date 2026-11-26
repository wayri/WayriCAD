"""Bounded, origin-scoped IPC selection following; no native objects in workers."""
import threading


class SelectionState:
    def __init__(self):
        self.last = None
        self.epoch = 0
        self.closed = False

    def changed(self, values, epoch, *, include_empty=False):
        if self.closed or epoch != self.epoch:
            return False
        value = tuple(sorted({str(item).casefold() for item in values}))
        if value == self.last:
            return False
        self.last = value
        return bool(value) or include_empty

    def reset(self):
        self.epoch += 1
        self.last = None


class SelectionFollower:
    def __init__(self, owner, toggle, read, apply, ready, failed, *, include_empty=False, interval_ms=1200):
        import wx
        self.wx = wx
        self.owner, self.toggle = owner, toggle
        self.read, self.apply, self.ready, self.failed = read, apply, ready, failed
        self.state = SelectionState()
        self.include_empty=include_empty
        self.running = False
        self.timer = wx.Timer(owner)
        owner.Bind(wx.EVT_TIMER, self.poll, self.timer)
        toggle.Bind(wx.EVT_CHECKBOX, self.changed)
        self.timer.Start(interval_ms)

    def changed(self, event=None):
        self.state.reset()
        if self.toggle.GetValue():
            self.poll()

    def stop(self):
        self.state.closed = True
        self.state.reset()
        self.timer.Stop()

    def poll(self, event=None):
        if self.state.closed or self.running or not self.toggle.GetValue() or not self.ready():
            return
        self.running = True
        epoch = self.state.epoch

        def work():
            values, error = (), None
            try:
                values = self.read()
            except Exception as caught:
                error = caught
            if not self.state.closed:
                try:
                    self.wx.CallAfter(self.finish, epoch, values, error)
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True, name='PCB selection read').start()

    def finish(self, epoch, values, error):
        self.running = False
        if self.state.closed or epoch != self.state.epoch or not self.toggle.GetValue():
            return
        if not self.ready():
            return
        if error is not None:
            self.toggle.SetValue(False)
            self.state.reset()
            self.failed(error)
        elif self.state.changed(values, epoch, include_empty=self.include_empty):
            try:
                self.apply(values)
            except Exception as caught:
                self.failed(caught)
