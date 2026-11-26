"""Background Trace RLC extraction from the originating editor's route."""
from dataclasses import dataclass

import wx
from wayricad_runtime.editor_refresh import source_stamp
from wayricad_runtime.live_pcb import capture_live_pcb, route_stamp
from wayricad_runtime.net_watch import NetWatch
from wayricad_runtime.saved_board import assert_current, load_board

from .bulk_ui import BulkController
from .measurement import TraceMeasurementEngine
from .origin_selection import TerminalIndex


@dataclass(frozen=True)
class WatchedPath:
    origin: object
    net: str
    endpoints: tuple[str, str]
    frequency: float
    reference: str
    mate: str

    @property
    def nets(self):
        return (self.net, self.mate) if self.mate else (self.net,)

    def stamp(self):
        route = route_stamp(self.origin.path, self.origin.launch_context, self.nets)
        return route, self.rules_stamp()

    def rules_stamp(self):
        return source_stamp(self.origin.path, ('.kicad_pro', '.kicad_dru'))

    def extract(self, expected, cancelled):
        rules = self.rules_stamp()
        with capture_live_pcb(self.origin.path, self.origin.launch_context, watch_nets=self.nets) as (path, evidence):
            baseline = (evidence['route_stamp'], rules)
            if cancelled() or (expected is not None and baseline != expected):
                return None
            board = load_board(path)
            if board is None:
                raise ValueError('KiCad could not read the editor copy.')
            engine = TraceMeasurementEngine(board)
            net, pads = TerminalIndex(board).restore(self.net, self.endpoints, engine.net_names())
            if net != self.net or not all(pads):
                raise ValueError('An endpoint was deleted, moved to a different net or became ambiguous. Save and review the selected route.')
            result = engine.measure(self.net, pads[0], pads[1], self.frequency, self.reference)
            mate_result = None
            if self.mate:
                mate_pads = engine.pads_for_net(self.mate)
                if len(mate_pads) >= 2:
                    mate_result = engine.measure(self.mate, mate_pads[0], mate_pads[-1], self.frequency, self.reference)
                else:
                    result.notes.append(f'Mate {self.mate} has fewer than two terminals; pair measurement unavailable.')
            assert_current(board)
        if cancelled() or self.stamp() != baseline:
            return None
        return board, result, mate_result, evidence, baseline


class RouteWatchMixin:
    def init_route_watch(self):
        self.watch_request = None
        self.watch_evidence = None
        self.watch_worker = BulkController()
        self.route_watch = NetWatch(self, lambda: self.watch_request.stamp(), self.watch_ready,
                                    self.run_watched_path, self.watch_unavailable)
        self.watch_path.Bind(wx.EVT_CHECKBOX, self.toggle_route_watch)

    def watch_ready(self):
        return (self.watch_request is not None and not self.source_dirty and not self.watch_worker.busy
                and self.IsShownOnScreen() and not self.IsIconized())

    def watch_unavailable(self, error):
        self._invalidate(None, keep_watch=True)
        self.watch_status.SetLabel(f'Live view unavailable. Waiting for the originating editor. {error}')
        self.route_watch.arm(())

    def toggle_route_watch(self, _event):
        if not self.watch_path.GetValue():
            self.stop_watching_path()
            self._invalidate(None)
            return
        try:
            self.check_source()
            net = self.net.GetValue()
            endpoints = tuple(self.terminal_index.ids(net, (self.start.GetValue(), self.end.GetValue())))
            if not all(endpoints) or endpoints[0] == endpoints[1]:
                raise ValueError('Choose two distinct, unambiguous endpoint pads.')
            frequency = float(self.frequency.GetValue())
            self.watch_request = WatchedPath(self.origin_selection, net, endpoints, frequency,
                                             self.reference.GetValue(), self._mate_net())
            self.run_watched_path()
        except ValueError as error:
            self.stop_watching_path(str(error))

    def stop_watching_path(self, message=''):
        self.route_watch.disarm()
        self.watch_worker.cancel()
        self.watch_request = None
        self.watch_path.SetValue(False)
        self.watch_status.SetLabel(message)

    def run_watched_path(self, expected=None):
        request = self.watch_request
        if request is None or self.watch_worker.busy:
            return
        self._invalidate(None, keep_watch=True)
        self.measure_button.Disable()
        self.watch_status.SetLabel('Analyzing current editor copper…')

        def finish(payload, error):
            if request is not self.watch_request:
                self.update_watch_controls()
                return
            self.update_watch_controls()
            if error or payload is None or self.source_dirty:
                self.watch_status.SetLabel(error or 'Routing changed during analysis. Waiting for a stable route…')
                if expected is None or not error:
                    self.route_watch.arm(())
                return
            self.route_preview.board, self.current, self.mate_result, self.watch_evidence, baseline = payload
            self._show(self.current, fit_view=expected is None)
            self.workflow.set_step(2, 'Review live geometry, per-section estimates, and notes.')
            self.watch_status.SetLabel('Watching ' + ' and '.join(request.nets) + ' in PCB Editor')
            self.route_watch.arm(baseline)

        self.watch_worker.start(lambda cancelled, _progress: request.extract(expected, cancelled), finish, wx.CallAfter)

    def update_watch_controls(self):
        a, b = self.start.GetValue(), self.end.GetValue()
        path_mode = self.mode.GetSelection() == 0
        ready = bool(not self.source_dirty and a and b and a != b and self.reference.GetValue()
                     and (self.diff_net.GetValue() if path_mode else self.zone_layer.GetSelection() != wx.NOT_FOUND))
        busy = self.saved_board and self.watch_worker.busy
        self.measure_button.Enable(ready and not busy)
        if self.saved_board:
            self.watch_path.Enable(ready and path_mode and self.origin_selection.available
                                   and (not busy or self.watch_request is not None))
