from wayricad_runtime.net_watch import NetChangeState


def test_unrelated_edits_and_initial_samples_do_not_dispatch():
    state = NetChangeState()
    assert not state.observe("initial")
    assert not state.observe("initial")
    assert state.baseline == "initial"


def test_changes_coalesce_until_two_observations_agree():
    state = NetChangeState("original")
    assert not state.observe("first-edit")
    assert not state.observe("second-edit")
    assert state.observe("second-edit")
    assert not state.observe("second-edit")
    assert state.baseline == "second-edit"


def test_undo_to_baseline_clears_pending_change():
    state = NetChangeState("original")
    assert not state.observe("edit")
    assert not state.observe("original")
    assert not state.observe("edit")
    assert state.observe("edit")

def test_rearm_discards_pending_sample_and_waits_for_ready(monkeypatch):
    import sys
    from types import SimpleNamespace

    from wayricad_runtime import net_watch

    class Timer:
        def __init__(self, owner):
            self.active = False

        def Start(self, interval):
            self.active = True

        def Stop(self):
            self.active = False

    callbacks, changes, errors = [], [], []
    samples = iter(("obsolete", "routed", "routed"))
    ready = True
    fake_wx = SimpleNamespace(
        Timer=Timer, EVT_TIMER=object(),
        CallAfter=lambda callback, *args: callbacks.append((callback, args)),
    )
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    monkeypatch.setattr(net_watch, "Thread", lambda target, args, **kwargs:
                        SimpleNamespace(start=lambda: target(*args)))
    owner = SimpleNamespace(Bind=lambda *args: None)
    watch = net_watch.NetWatch(owner, lambda: next(samples), lambda: ready,
                               changes.append, errors.append)

    def deliver():
        callback, args = callbacks.pop(0)
        callback(*args)

    watch.arm("first")
    watch.poll()
    watch.arm("second")
    watch.poll()
    assert len(callbacks) == 1
    deliver()
    ready = False
    watch.poll()
    assert not callbacks
    ready = True
    for _ in range(2):
        watch.poll()
        deliver()
    assert changes == ["routed"]
    assert not errors
    watch.stop()
    watch.poll()
    assert not callbacks
