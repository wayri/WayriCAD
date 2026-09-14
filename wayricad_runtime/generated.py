"""Review/apply lifecycle shared by generated heater and winding geometry."""
from .geometry import board_fingerprint
from .operations import add_group, remove_group


class ReviewedGeometry:
    def _settings_signature(self):
        controls = dict(self.fields)
        for key in ('pattern','shape','connection','core','net','secondary_net'):
            if hasattr(self,key):controls[key]=getattr(self,key)
        return tuple((key, control.GetValue() if hasattr(control,'GetValue') else control.GetStringSelection())
                     for key,control in sorted(controls.items()))

    def _capture_review(self):
        self._review_settings = self._settings_signature()
        self._review_board = board_fingerprint(self.board)
        self.preview_items = []

    def _check_review(self):
        if not self.result:
            raise ValueError('Generate and review the geometry first.')
        if getattr(self,'_review_settings',None) != self._settings_signature():
            raise ValueError('Settings changed. Generate a new preview before applying.')
        if self._review_board != board_fingerprint(self.board):
            raise ValueError('The PCB changed. Generate a new preview before applying.')

    def _unattached_items(self):
        return self._board_items() if hasattr(self,'_board_items') else self._make_items()

    def _report_error(self, exc):
        import wx
        # Retain references if native rollback is incomplete.
        self.recovery_error = exc
        wx.MessageBox(str(exc), 'WayriCAD — operation stopped', wx.OK | wx.ICON_ERROR)

    def show_pcb(self, _event):
        try:
            self._check_review()
            self.preview_items = self._unattached_items()
            self.status.SetLabel(f'{len(self.preview_items)} items prepared. PCB unchanged until Apply.')
        except Exception as exc:self._report_error(exc)

    def clear_preview(self, _event):
        self.preview_items = []

    def _new_group(self, items, name=''):
        import pcbnew
        return add_group(self.board, items, name or f'{self.group_prefix} {len(self._persistent_groups())+1:03d}', pcbnew.PCB_GROUP)

    def commit(self, _event):
        import pcbnew
        try:
            self._check_review()
            items = self._unattached_items()
            group = self._new_group(items)
            self.undo_stack.append(group)
            self.redo_stack.clear()
            self.preview_items = []
            self._review_board = None  # A second apply requires a new explicit review.
            pcbnew.Refresh()
            self.status.SetLabel(f'Applied {len(items)} items. Run KiCad DRC before fabrication.')
        except Exception as exc:self._report_error(exc)

    def undo(self, _event):
        import pcbnew
        if not self.undo_stack:return
        try:
            group = self.undo_stack[-1]
            items = self._group_items(group)
            name = group.GetName()
            remove_group(self.board, group, items)
            self.undo_stack.pop()
            self.redo_stack.append((name, items))
            self.status.SetLabel(f'Undid {len(items)} items.')
            pcbnew.Refresh()
        except Exception as exc:self._report_error(exc)

    def redo(self, _event):
        import pcbnew
        if not self.redo_stack:return
        try:
            name, items = self.redo_stack[-1]
            group = self._new_group(items,name)
            self.redo_stack.pop()
            self.undo_stack.append(group)
            self.status.SetLabel(f'Redid {len(items)} items.')
            pcbnew.Refresh()
        except Exception as exc:self._report_error(exc)
