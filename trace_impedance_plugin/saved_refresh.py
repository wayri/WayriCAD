"""Replace a saved Trace RLC snapshot while retaining physical endpoint identity."""
import wx

from wayricad_runtime.editor_refresh import SavedBoardRefresh, source_stamp
from wayricad_runtime.saved_board import assert_current, load_board
from wayricad_runtime.selection_follow import SelectionFollower
from .bulk_ui import BulkController
from .measurement import TraceMeasurementEngine
from .origin_selection import OriginSelection, TerminalIndex


class SavedRefreshMixin:
    def start_saved_refresh(self):
        self.refresh_worker = BulkController()
        self.terminal_index = TerminalIndex(self.board)
        self.selection_follower = SelectionFollower(
            self, self.auto_refresh, lambda: self.origin_selection.read(), self.follow_selection,
            lambda: not self.source_dirty and not self.selection_worker.busy,
            self.follow_error, include_empty=True)
        self.auto_refresh.Bind(wx.EVT_CHECKBOX, self._follow_toggled)
        self.source_refresh = SavedBoardRefresh(
            self, self.origin_selection.path, self.invalidate_source, self.reload_source,
            lambda: not self.refresh_worker.busy and not self.selection_worker.busy)
        # The board may have changed while the controls and native inventory were built.
        self.source_refresh.state.reset(self.origin_selection.stamp)

    def invalidate_source(self):
        self.source_dirty = True
        self.selection_follower.state.reset()
        self._invalidate(None)
        self.config_scroll.Disable()
        self.measure_button.Disable()
        self.summary.SetLabel("Saved inputs changed. Reloading the PCB and rules…")

    def check_source(self):
        if self.saved_board:
            if self.source_dirty:
                raise ValueError("Wait for the saved PCB to reload, then review your endpoints.")
            self.origin_selection.check_source()
        assert_current(self.board)

    def reload_source(self, event=None):
        if self.refresh_worker.busy:
            return
        self.invalidate_source()
        origin = self.origin_selection
        stamp = source_stamp(origin.path)
        def read(cancel, progress):
            board = load_board(origin.path)
            if board is None:
                raise ValueError("KiCad could not load this PCB.")
            engine = TraceMeasurementEngine(board)
            names = engine.net_names()
            engine.ground_nets()
            engine.stackup_layers()
            terminals = TerminalIndex(board)
            assert_current(board)
            return board, engine, names, terminals

        def finish(payload, error):
            if source_stamp(origin.path) != stamp:
                return
            if error:
                self.summary.SetLabel("PCB reload failed. Use More → Reload saved PCB to retry. " + error)
                return
            old_net = self.net.GetValue()
            old_ids = self.terminal_index.ids(old_net, (self.start.GetValue(), self.end.GetValue()))
            previous_ref, previous_mate = self.reference.GetValue(), self.diff_net.GetValue()
            old_island = self.zone_layer.GetSelection()
            zone = self.zone_options[old_island]['id'] if old_island >= 0 else None
            self.board, self.engine, self.all_net_names, self.terminal_index = payload
            self.route_preview.board = self.board
            self.origin_selection = OriginSelection(origin.path, launch_context=origin.launch_context, stamp=stamp)
            net, ends = self.terminal_index.restore(old_net, old_ids, self.all_net_names)
            query = self.net_search.GetValue().strip().casefold()
            if net and query not in net.casefold():
                self.net_search.ChangeValue("")
                query = ""
            self.net.SetItems([n for n in self.all_net_names if query in n.casefold()])
            self.net.SetSelection(self.net.FindString(net, True) if net else wx.NOT_FOUND)
            self.diff_net.SetItems(["<none>", *self.all_net_names])
            self._load_pads(None)
            if self.mode.GetSelection() == 1:
                # Island indices can change after refilling a zone. Retain only the
                # unique island of that zone/layer containing the same two terminals.
                indices = [i for i,row in enumerate(self.zone_options)
                           if zone and row['id'].rsplit(':',1)[0] == zone.rsplit(':',1)[0]
                           and all(ends) and set(ends) <= set(self.engine.zone_terminals(row['id']))]
                self.zone_layer.SetSelection(indices[0] if len(indices) == 1 else wx.NOT_FOUND)
                self._zone_changed(None)
            for control, label in zip((self.start,self.end), ends):
                control.SetSelection(control.FindString(label,True) if label else wx.NOT_FOUND)
            self._load_stackup()
            self.reference.SetSelection(self.reference.FindString(previous_ref,True))
            if not self.auto_pair.GetValue():
                self.diff_net.SetSelection(self.diff_net.FindString(previous_mate,True))
            self.source_dirty = False
            self.config_scroll.Enable()
            self._terminal_changed()
            self.summary.SetLabel("PCB refreshed. " + ("Ready to analyze the selected path."
                                  if self.measure_button.IsEnabled() else "Review the missing route inputs."))
        self.refresh_worker.start(read, finish, wx.CallAfter)

    def follow_error(self, error):
        self.follow_selection(())
        self.summary.SetLabel(str(error))

    def follow_selection(self, identifiers):
        self.route_preview.followed_ids = frozenset(identifiers)
        self.route_preview.selected_uuid = None
        self.route_preview.Refresh()
