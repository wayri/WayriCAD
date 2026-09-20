"""WayriCAD visual entry point for the staged Constraint Studio engine."""
from __future__ import annotations

import math
from pathlib import Path

import wx

from .constraint_studio.inspection import items_from_board
from .constraint_studio.linked_areas import all_areas, area_polygon
from .constraint_studio.ui import StudioFrame
from .studio_bridge import overview, scope_preview, stage_protocol_rules

INK = '#17253C'
BLUE = '#2376D2'
AMBER = '#B86E0A'
RED = '#B83A40'


class ScopeCanvas(wx.Panel):
    """Pan/zoom schematic scope map. Colour communicates condition results only."""
    def __init__(self, parent, on_pick):
        super().__init__(parent)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((300, 220))
        self.rows = []
        self.on_pick = on_pick
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.drag = None
        self.pick_points = []
        self.regions = []
        self.Bind(wx.EVT_PAINT, self.paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))
        self.Bind(wx.EVT_MOUSEWHEEL, self.wheel)
        self.Bind(wx.EVT_LEFT_DOWN, self.down)
        self.Bind(wx.EVT_LEFT_UP, self.up)
        self.Bind(wx.EVT_MOTION, self.motion)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda event: setattr(self, 'drag', None))
        self.SetToolTip('Wheel to zoom; drag to pan; click an item for its scope result.')

    def set_rows(self, rows, fit=False):
        self.rows = rows
        if fit:
            self.fit()
        self.Refresh()

    def fit(self, event=None):
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.Refresh()

    def wheel(self, event):
        self.zoom = max(.2, min(30, self.zoom * (1.2 if event.GetWheelRotation() > 0 else 1 / 1.2)))
        self.Refresh()

    def down(self, event):
        self.drag = (event.GetPosition(), tuple(self.pan))
        self.CaptureMouse()

    def motion(self, event):
        if self.drag and event.Dragging():
            start, pan = self.drag
            pos = event.GetPosition()
            self.pan = [pan[0] + pos.x - start.x, pan[1] + pos.y - start.y]
            self.Refresh()

    def up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        if self.drag:
            start, _ = self.drag
            pos = event.GetPosition()
            if math.hypot(pos.x - start.x, pos.y - start.y) < 4 and self.pick_points:
                distance, index = min((math.hypot(pos.x - x, pos.y - y), i) for x, y, i in self.pick_points)
                if distance < 18:
                    self.on_pick(self.rows[index])
        self.drag = None

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush('#F1F5FA')); dc.Clear()
        dc.SetTextForeground(INK)
        points = [point for item, _, _ in self.rows for point in item.points]
        points.extend(point for _, polygon in self.regions for point in polygon)
        if not points:
            dc.DrawText('Open a saved board to see its scope map.', 20, 20)
            return
        width, height = self.GetClientSize()
        xs, ys = zip(*points)
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        scale = max(.01, min(max(1, width - 70) / max(1, max(xs) - min(xs)),
                             max(1, height - 70) / max(1, max(ys) - min(ys)))) * self.zoom
        def screen(point):
            return (round(width / 2 + (point[0] - cx) * scale + self.pan[0]),
                    round(height / 2 + (point[1] - cy) * scale + self.pan[1]))
        self.pick_points = []
        dc.SetPen(wx.Pen('#7C8DA4', 1, wx.PENSTYLE_SHORT_DASH))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        for name, polygon in self.regions:
            if len(polygon) < 3: continue
            outline = [screen(point) for point in polygon]
            dc.DrawLines(outline + outline[:1])
            dc.SetTextForeground('#53647A')
            dc.DrawText(name, outline[0][0] + 6, outline[0][1] - 18)
        dc.SetTextForeground(INK)
        # Dim context first, highlighted and unknown objects on top.
        for index in sorted(range(len(self.rows)), key=lambda i: self.rows[i][1] is not False):
            item, state, _ = self.rows[index]
            if not item.points:
                continue
            color = BLUE if state is True else AMBER if state is None else '#B8C2D1'
            pts = [screen(point) for point in item.points]
            x, y = screen((sum(p[0] for p in item.points) / len(item.points),
                           sum(p[1] for p in item.points) / len(item.points)))
            self.pick_points.append((x, y, index))
            dc.SetPen(wx.Pen(color, 3 if state is True else 1))
            dc.SetBrush(wx.Brush(color))
            if item.kind == 'Track':
                # Curved tracks are shown as a chord, never as exact copper.
                if item.geometry == 'unknown':
                    dc.SetPen(wx.Pen(color, 1, wx.PENSTYLE_SHORT_DASH))
                dc.DrawLines(pts)
            elif item.kind == 'Footprint':
                dc.SetBrush(wx.TRANSPARENT_BRUSH)
                dc.DrawRectangle(x - 5, y - 5, 10, 10)
                dc.DrawText(item.reference, x + 7, y - 8)
            else:
                dc.DrawCircle(x, y, 4 if item.kind == 'Pad' else 3)


class OverviewPanel(wx.Panel):
    def __init__(self, parent, studio):
        super().__init__(parent)
        self.studio = studio
        self.rule_indices = []
        self.items = []
        self.context_key = None
        self.loading = False
        root = wx.BoxSizer(wx.VERTICAL); self.SetSizer(root)
        self.cards = []
        cards = wx.BoxSizer(wx.HORIZONTAL)
        for caption in ('Enabled rules', 'Local errors', 'Warnings', 'Changed files'):
            card = wx.Panel(self); card.SetBackgroundColour('white')
            box = wx.BoxSizer(wx.VERTICAL); card.SetSizer(box)
            value = wx.StaticText(card, label='0'); value.SetFont(value.GetFont().Scaled(1.8).Bold())
            box.Add(value, 0, wx.ALL, 8); box.Add(wx.StaticText(card, label=caption), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
            cards.Add(card, 1, wx.EXPAND | wx.RIGHT, 8); self.cards.append(value)
        root.Add(cards, 0, wx.EXPAND | wx.ALL, 12)
        bar = wx.WrapSizer(wx.HORIZONTAL)
        for title, handler in [('Protocol presets…', studio.open_protocols), ('Edit selected rule', self.edit_rule),
                               ('Review changes…', studio.show_review), ('Fit map', lambda event: self.canvas.fit()),
                               ('Refresh', lambda event: self.refresh())]:
            button = wx.Button(self, label=title); button.Bind(wx.EVT_BUTTON, handler); bar.Add(button, 0, wx.RIGHT | wx.BOTTOM, 6)
        root.Add(bar, 0, wx.LEFT | wx.RIGHT, 12)
        self.status = wx.StaticText(self, label='Saved source → staged edits → review export → native DRC → offline apply')
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 12)
        split = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        self.rules = wx.ListCtrl(split, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (name, size) in enumerate((('Rule · highest priority first', 245), ('State', 90))):
            self.rules.InsertColumn(i, name, width=size)
        self.rules.Bind(wx.EVT_LIST_ITEM_SELECTED, self.select_rule)
        self.rules.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.edit_rule)
        right = wx.Panel(split); rs = wx.BoxSizer(wx.VERTICAL); right.SetSizer(rs)
        legend = wx.StaticText(right, label='SCOPE MAP  ·  Blue: condition match  |  Amber: unknown  |  Gray: no match')
        rs.Add(legend, 0, wx.ALL, 8)
        self.canvas = ScopeCanvas(right, self.pick_item); rs.Add(self.canvas, 1, wx.EXPAND)
        self.scope_status = wx.StaticText(right, label='Select a rule.'); rs.Add(self.scope_status, 0, wx.EXPAND | wx.ALL, 8)
        self.detail = wx.TextCtrl(right, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 68))
        rs.Add(self.detail, 0, wx.EXPAND | wx.ALL, 8)
        rs.Add(wx.StaticText(right, label='Saved/staged schematic geometry; pad sizes and arcs are simplified.\nCondition matches are not violations or native effective-rule results.'), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        split.SplitVertically(self.rules, right, 350); split.SetMinimumPaneSize(240)
        root.Add(split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.findings = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 120))
        for i, (name, size) in enumerate((('Lint', 80), ('Rule / scope', 220), ('Finding · double-click for details', 780))):
            self.findings.InsertColumn(i, name, width=size)
        self.findings.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.open_finding)
        root.Add(self.findings, 0, wx.EXPAND | wx.ALL, 12)

    def refresh(self):
        self.studio.collect()
        w = self.studio.w
        summary = overview(w)
        for label, value, color in zip(self.cards, (summary['enabled'], summary['errors'], summary['warnings'], len(summary['changed'])),
                                       (BLUE, RED if summary['errors'] else INK, AMBER if summary['warnings'] else INK, BLUE)):
            label.SetLabel(str(value)); label.SetForegroundColour(color)
        changed = ', '.join(summary['changed']) or 'none'
        self.status.SetLabel('Changed files: ' + changed + '   |   Source files untouched; native DRC required on the exported copy.')
        self.loading = True
        selected = self.selected_index()
        self.rules.DeleteAllItems(); self.rule_indices = []
        for index in reversed(range(len(w.document.rules))):
            rule = w.document.rules[index]
            row = self.rules.InsertItem(self.rules.GetItemCount(), rule.name)
            self.rules.SetItem(row, 1, 'Enabled' if rule.enabled else 'Disabled')
            if not rule.enabled: self.rules.SetItemTextColour(row, '#78848F')
            self.rule_indices.append(index)
        if self.rule_indices:
            self.rules.Select(self.rule_indices.index(selected) if selected in self.rule_indices else 0)
        self.loading = False
        self.issue_rows = summary['issues']; self.findings.DeleteAllItems()
        for issue in self.issue_rows:
            row = self.findings.InsertItem(self.findings.GetItemCount(), issue.severity.upper())
            self.findings.SetItem(row, 1, issue.rule); self.findings.SetItem(row, 2, issue.message)
            self.findings.SetItemTextColour(row, RED if issue.severity == 'error' else AMBER if issue.severity == 'warning' else INK)
        # Reuse parsed board objects until geometry/project membership changes.
        key = (w.board_text, repr(w.project))
        fit = key != self.context_key
        if fit:
            self.items = items_from_board(w.context, w.project); self.context_key = key
            self.canvas.regions = []
            for area in all_areas(w.context):
                if not area.get('rule_area'): continue
                try: self.canvas.regions.append((area['name'], area_polygon(area)))
                except ValueError: pass  # Complex outlines stay in native geometry review.
        self.update_scope(fit)
        self.Layout()

    def selected_index(self):
        row = self.rules.GetFirstSelected()
        return self.rule_indices[row] if 0 <= row < len(self.rule_indices) else None

    def select_rule(self, event):
        if not self.loading: self.update_scope()

    def update_scope(self, fit=False):
        index = self.selected_index()
        rows = scope_preview(self.studio.w, index, self.items)
        self.canvas.set_rows(rows, fit)
        matched = sum(state is True for _, state, _ in rows)
        unknown = sum(state is None for _, state, _ in rows)
        self.scope_status.SetLabel(f'{matched} matching items  ·  {unknown} unknown  ·  {len(rows)} items in saved snapshot')
        self.detail.ChangeValue(self.studio.w.document.rules[index].condition or 'All objects' if index is not None else 'Select a rule to preview its condition.')

    def pick_item(self, row):
        item, state, reasons = row
        status = 'Condition match' if state is True else 'No condition match' if state is False else 'Native evaluation required'
        self.detail.ChangeValue(item.label + '\n' + status + ('\n' + '; '.join(reasons) if reasons else ''))

    def edit_rule(self, event):
        index = self.selected_index()
        if index is not None:
            self.studio.collect(); self.studio.load_rule(index); self.studio.select_page(self.studio.rule_page)

    def open_finding(self, event):
        issue = self.issue_rows[event.GetIndex()]
        wx.MessageBox(issue.message, issue.severity.upper() + ' — ' + issue.rule, wx.OK, self)


class ConstraintStudioFrame(StudioFrame):
    def __init__(self, parent=None, board_path='', board=None):
        self.live_board = board
        super().__init__(parent, board_path)
        self.SetTitle('WayriCAD Constraint Studio · staged project rules')
        self.overview_panel = OverviewPanel(self.book, self)
        self.book.InsertPage(0, self.overview_panel, 'Visual overview', True)
        self.overview_panel.refresh()
        area = wx.GetClientDisplayRect()
        self.SetSize((min(1500, area.width - 32), min(940, area.height - 48)))
        self.Center()
        self.visual = None
        try:
            from .studio_webview import VisualWorkspace
            self.visual = VisualWorkspace(self)
        except (ImportError, RuntimeError) as exc:
            self.SetStatusText('Visual shell unavailable; full native workspace is available. ' + str(exc))

    def page_changed(self, event):
        super().page_changed(event)
        if hasattr(self, 'overview_panel') and self.book.GetCurrentPage() is self.overview_panel:
            self.overview_panel.refresh()

    def load(self, path):
        super().load(path)
        self.SetTitle('WayriCAD Constraint Studio · ' + Path(path).name)
        if hasattr(self, 'overview_panel'): self.overview_panel.refresh()

    def open_protocols(self, event):
        from .protocol_constraint_composer_plugin import ConstraintFrame
        # The protocol workflow uses this same saved snapshot, including after Open board.
        frame = ConstraintFrame(self, None)
        frame.detect(None)
        frame.Show()

    def stage_protocols(self, text):
        self.collect()
        trial = self.w.clone()
        stage_protocol_rules(trial, text)
        self.checkpoint(); self.w = trial
        self.index = None; self.editing = None; self.refresh_rules()
        self.overview_panel.refresh(); self.select_page(self.overview_panel)
        if getattr(self, 'visual', None): self.visual.show()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='WayriCAD Constraint Studio (saved-project editor)')
    parser.add_argument('board', nargs='?', default='')
    args = parser.parse_args()
    app = wx.App(False)
    frame = ConstraintStudioFrame(board_path=args.board)
    frame.Show(); app.MainLoop()


if __name__ == '__main__':
    main()
