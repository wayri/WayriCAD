"""Synchronize a saved EM study and its rule-area identity with its launching editor."""
import threading

from wayricad_runtime.context import LaunchContext, redact_error
from wayricad_runtime.editor_refresh import SavedBoardRefresh, source_stamp


def area_index(areas, identifiers):
    """Accept exactly one selected item that identifies exactly one saved rule area."""
    ids = tuple(identifiers)
    if len(ids) != 1:
        return -1
    matches = [i for i, area in enumerate(areas) if area['id'].casefold() == ids[0].casefold()]
    return matches[0] if len(matches) == 1 else -1


class BoardSync:
    def __init__(self, frame):
        self.frame = frame
        self.origin = LaunchContext.capture()
        self.selecting = False
        self.discard_run = False
        self.region_choices = None
        self.watcher = SavedBoardRefresh(frame, frame.session.board, self.invalidate, self.reload,
                                         lambda: not (frame.closed or frame.running or frame.region_busy))
        for button in frame.pcb_selection_buttons:
            button.Enable(bool(self.origin.socket and self.origin.token))
            if not button.IsEnabled():
                button.SetToolTip('Open Quick EMerge from PCB Editor to use its rule-area selection.')

    def invalidate(self):
        f = self.frame
        if f.region_listing:
            areas = f.region_listing['areas']
            index = f.rule_area.GetSelection()
            self.region_choices = (areas[index]['id'] if 0 <= index < len(areas) else '',
                                   f.signal_net.GetStringSelection(), f.reference_net.GetStringSelection())
        f.region_listing = None
        if f.mode.GetSelection() == 2:
            f.region_material_review.SetValue(False)
        f.rule_area.Clear()
        f.signal_net.Clear()
        f.reference_net.Clear()
        f._pending_region_file = None
        if f.region_busy:
            f.region_cancel.set()
        if f.running:
            self.discard_run = True
            process = f.session.process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        f.invalidate()
        f.SetStatusText('Saved board or rules changed. Previous results cleared.')

    def reload(self):
        f = self.frame
        if f.mode.GetSelection() == 2:
            f.load_rule_areas()
        else:
            f.SetStatusText('Saved board refreshed. Preview the current template to run it again.')

    def restore_choices(self, listing):
        if self.region_choices is None:
            return False
        area, signal, reference = self.region_choices
        self.region_choices = None
        f = self.frame
        f.rule_area.SetSelection(area_index(listing['areas'], (area,)))
        for control, name in ((f.signal_net, signal), (f.reference_net, reference)):
            control.SetSelection(control.FindString(name, True) if name else -1)
        return any(control.GetSelection() < 0 for control in (f.rule_area, f.signal_net, f.reference_net))

    def highlight(self):
        from . import region_view
        f = self.frame
        listing = f.region_listing
        index = f.rule_area.GetSelection()
        if not listing:
            return
        area = listing['areas'][index]['id'] if 0 <= index < len(listing['areas']) else ''
        options = dict(f.display_options, selected_rule_area=area)
        f.viewports['PCB enclosure'].render(region_view.board_context, listing, options=options)
        f.select_view('PCB enclosure')

    def select(self, from_editor):
        import wx
        from wayricad_runtime.analysis_selection import SavedSelectionReader, select_origin
        f = self.frame
        self.watcher.poll()
        listing = f.region_listing
        if self.selecting or f.region_busy or f.running or not listing:
            f.SetStatusText('Load the saved rule areas and finish the current operation first.')
            return
        index = f.rule_area.GetSelection()
        if not from_editor and not 0 <= index < len(listing['areas']):
            f.SetStatusText('Choose a saved enclosure to highlight in PCB Editor.')
            return
        sha = listing['source']['sha256']
        board = f.session.board
        stamp = source_stamp(board)
        self.selecting = True

        def finish(selected, error):
            self.selecting = False
            if f.closed or f.region_listing is not listing or stamp != source_stamp(board):
                return
            if error:
                f.SetStatusText(redact_error(error))
            elif from_editor:
                chosen = area_index(listing['areas'], selected)
                if chosen < 0:
                    f.SetStatusText('Select exactly one saved rule area in the originating PCB Editor.')
                    return
                if f.rule_area.GetSelection() != chosen:
                    f.rule_area.SetSelection(chosen)
                    f.invalidate()
                self.highlight()
                f.SetStatusText('Selected PCB enclosure: ' + f.rule_area.GetStringSelection())
            else:
                f.SetStatusText('Enclosure selected in the originating PCB Editor.')

        def work():
            try:
                if from_editor:
                    ids = SavedSelectionReader(board, expected_sha256=sha, launch_context=self.origin).read()
                else:
                    select_origin(board, [listing['areas'][index]['id']], expected_sha256=sha,
                                  focus=True, launch_context=self.origin)
                    ids = ()
                wx.CallAfter(finish, ids, None)
            except Exception as exc:
                wx.CallAfter(finish, (), exc)
        threading.Thread(target=work, name='EMerge rule-area selection', daemon=True).start()
