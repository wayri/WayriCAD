"""Resizable native interface for bounded local language plans and report results."""
from pathlib import Path
import hashlib
import threading
import wx
import wx.lib.scrolledpanel as scrolled

EXAMPLES = (
    'List available tools',
    'Check mechanical clearances',
    'Preview component fanout',
    'Calculate microstrip impedance',
)


def action_icon(button, art):
    """Keep platform-native action symbols paired with readable text labels."""
    try:
        from wayricad_runtime.visual_feedback import decorate_button
        roles = {wx.ART_FIND: 'search', wx.ART_GO_FORWARD: 'run', wx.ART_CROSS_MARK: 'cancel',
                 wx.ART_FILE_OPEN: 'open', wx.ART_FOLDER_OPEN: 'open', wx.ART_FOLDER: 'open',
                 wx.ART_HELP: 'help', wx.ART_DELETE: 'clear', wx.ART_GO_HOME: 'preview'}
        return decorate_button(button, roles.get(art))
    except ImportError:
        pass
    bitmap = wx.ArtProvider.GetBitmap(art, wx.ART_BUTTON, (16, 16))
    if bitmap.IsOk():
        button.SetBitmap(bitmap)
        button.SetBitmapMargins(4, 0)
    return button


def report_path(artifact, output_root):
    """Accept only an existing generated file inside this run's output folder."""
    root = Path(output_root).resolve()
    candidate = Path(artifact['path'])
    candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError('This report is missing or is outside the results folder.')
    if candidate.suffix.lower() not in {'.html', '.htm', '.pdf', '.png', '.svg', '.json', '.txt', '.csv'}:
        raise ValueError('This result type cannot be opened from the Assistant.')
    return candidate


class AssistantFrame(wx.Frame):
    """Plan in a worker, explain missing inputs, execute and show generated evidence."""

    def __init__(self, parent=None, board=None, *, engine=None, output_root=None):
        super().__init__(parent, title='WayriCAD Assistant', size=(1120, 800))
        icon = Path(__file__).parent / 'icon.png'
        if icon.is_file():
            self.SetIcon(wx.Icon(str(icon), wx.BITMAP_TYPE_PNG))
        self.SetMinSize((720, 540))
        self.engine = engine
        self.output_root = Path(output_root) if output_root else (
            Path(wx.StandardPaths.Get().GetDocumentsDir()) / 'WayriCAD' / 'Assistant' / 'results')
        self.context = {}
        self.plan = None
        self.answers = {}
        self.question_controls = {}
        self.artifacts = []
        self.result_root = self.output_root
        self.result_parent = self.output_root
        self.cancel_event = threading.Event()
        self.closed = False
        self.busy = False
        self.run_thread = None
        self.loaded_board = None
        self.board_sha256 = None
        self._generation = 0
        self._all_focus_points = []
        self._selection_targets = []
        panel = wx.Panel(self)
        body = wx.BoxSizer(wx.VERTICAL)
        self.body = body
        heading = wx.StaticText(panel, label='What would you like to check?')
        font = heading.GetFont(); font.SetPointSize(font.GetPointSize() + 5); font.MakeBold()
        heading.SetFont(font)
        body.Add(heading, 0, wx.ALL, 12)
        body.Add(wx.StaticText(panel, label='Local fuzzy commands · no cloud or language-model download · saved board stays unchanged'),
                 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        context_row = wx.BoxSizer(wx.HORIZONTAL)
        context_row.Add(wx.StaticText(panel, label='Saved PCB'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.board_path = wx.TextCtrl(panel, style=wx.TE_READONLY)
        context_row.Add(self.board_path, 1, wx.RIGHT, 6)
        self.choose = wx.Button(panel, label='Choose PCB…')
        self.choose.Bind(wx.EVT_BUTTON, self._choose)
        action_icon(self.choose, wx.ART_FILE_OPEN)
        context_row.Add(self.choose)
        body.Add(context_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.query = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 72))
        self.query.SetHint('For example: calculate microstrip impedance')
        self.query.SetToolTip('Describe one supported check. Missing numerical inputs are asked below; nothing is guessed silently.')
        body.Add(self.query, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.ask = wx.Button(panel, label='Ask Assistant')
        self.ask.Bind(wx.EVT_BUTTON, self._ask)
        self.run = wx.Button(panel, label='Run plan')
        self.run.Bind(wx.EVT_BUTTON, self._run)
        self.run.Disable()
        self.cancel = wx.Button(panel, label='Cancel')
        self.cancel.Bind(wx.EVT_BUTTON, lambda event: self._cancel())
        self.cancel.Disable()
        for button, art in ((self.ask, wx.ART_FIND), (self.run, wx.ART_GO_FORWARD), (self.cancel, wx.ART_CROSS_MARK)):
            action_icon(button, art)
        for item in (self.ask, self.run, self.cancel):
            actions.Add(item, 0, wx.RIGHT, 6)
        self.auto = wx.CheckBox(panel, label='Run ready read-only checks automatically')
        self.auto.SetValue(True)
        body.Add(actions, 0, wx.ALL, 12)
        body.Add(self.auto, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        example_row = wx.BoxSizer(wx.HORIZONTAL)
        example_row.Add(wx.StaticText(panel, label='Try'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.examples = wx.Choice(panel, choices=['Choose an example…', *EXAMPLES])
        self.examples.SetSelection(0)
        self.examples.Bind(wx.EVT_CHOICE, self._example)
        example_row.Add(self.examples, 1)
        help_button = wx.Button(panel, label='Help')
        help_button.Bind(wx.EVT_BUTTON, self._help)
        action_icon(help_button, wx.ART_HELP)
        example_row.Add(help_button, 0, wx.LEFT, 8)
        body.Add(example_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.tabs = wx.Notebook(panel)
        self.tabs.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._tab_changed)
        from wayricad_runtime.visual_feedback import bitmap
        icon_size = self.tabs.FromDIP((16, 16))
        self.tab_icons = wx.ImageList(*icon_size)
        for role in ('settings', 'report', 'preview'):
            self.tab_icons.Add(bitmap(role, self.tabs))
        self.tabs.AssignImageList(self.tab_icons)
        plan_page = scrolled.ScrolledPanel(self.tabs)
        plan_box = wx.BoxSizer(wx.VERTICAL)
        self.plan_summary = wx.StaticText(plan_page, label='No plan yet · choose a check to begin')
        font = self.plan_summary.GetFont(); font.MakeBold(); self.plan_summary.SetFont(font)
        plan_box.Add(self.plan_summary, 0, wx.EXPAND | wx.ALL, 8)
        self.plan_tasks = wx.ListCtrl(plan_page, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 94))
        self.plan_tasks.InsertColumn(0, 'Check', width=270)
        self.plan_tasks.InsertColumn(1, 'Target', width=240)
        self.plan_tasks.InsertColumn(2, 'State', width=140)
        task_icons = wx.ImageList(*self.plan_tasks.FromDIP((16, 16)))
        task_icons.Add(bitmap('success', self.plan_tasks))
        task_icons.Add(bitmap('warning', self.plan_tasks))
        self.plan_tasks.AssignImageList(task_icons, wx.IMAGE_LIST_SMALL)
        plan_box.Add(self.plan_tasks, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.plan_text = wx.TextCtrl(plan_page, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.plan_text.SetMinSize((-1, 100))
        self.plan_text.SetValue('Choose a PCB, then type a request. The Assistant shows its interpretation and asks for any missing inputs.\n\nIt coordinates existing CLI tools; it does not invent simulation settings or edit your layout.')
        plan_box.Add(self.plan_text, 1, wx.EXPAND | wx.ALL, 8)
        self.questions = scrolled.ScrolledPanel(plan_page, size=(-1, 150))
        self.question_sizer = wx.BoxSizer(wx.VERTICAL)
        self.questions.SetSizer(self.question_sizer)
        self.questions.SetupScrolling(scroll_x=False)
        plan_box.Add(self.questions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.questions.Hide()
        plan_page.SetSizer(plan_box)
        plan_page.SetupScrolling(scroll_x=False)
        self.tabs.AddPage(plan_page, 'Plan && inputs', imageId=0)
        result_page = wx.Panel(self.tabs)
        result_box = wx.BoxSizer(wx.VERTICAL)
        self.result_summary = wx.StaticText(result_page, label='No results yet')
        font = self.result_summary.GetFont(); font.MakeBold(); self.result_summary.SetFont(font)
        result_box.Add(self.result_summary, 0, wx.ALL, 8)
        self.results = wx.TextCtrl(result_page, style=wx.TE_MULTILINE | wx.TE_READONLY)
        result_box.Add(self.results, 1, wx.EXPAND | wx.ALL, 8)
        self.report_list = wx.ListBox(result_page)
        self.report_list.SetToolTip('Select a generated report, then open it. Reports are retained in this run’s results folder.')
        result_box.Add(self.report_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        report_actions = wx.BoxSizer(wx.HORIZONTAL)
        open_report = wx.Button(result_page, label='Open selected report')
        open_report.Bind(wx.EVT_BUTTON, self._open_report)
        action_icon(open_report, wx.ART_GO_FORWARD)
        report_actions.Add(open_report, 0, wx.RIGHT, 8)
        self.choose_output = wx.Button(result_page, label='Results folder…')
        self.choose_output.SetToolTip(str(self.output_root))
        self.choose_output.Bind(wx.EVT_BUTTON, self._choose_output)
        action_icon(self.choose_output, wx.ART_FOLDER_OPEN)
        report_actions.Add(self.choose_output, 0, wx.RIGHT, 8)
        self.open_output = wx.Button(result_page, label='Open results folder')
        self.open_output.Bind(wx.EVT_BUTTON, self._open_output)
        action_icon(self.open_output, wx.ART_FOLDER)
        report_actions.Add(self.open_output)
        result_box.Add(report_actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.report_list.Bind(wx.EVT_LISTBOX_DCLICK, self._open_report)
        result_page.SetSizer(result_box)
        self.tabs.AddPage(result_page, 'Results && reports', imageId=1)
        board_page = wx.Panel(self.tabs)
        board_box = wx.BoxSizer(wx.VERTICAL)
        self.preview_load = wx.Button(board_page, label='Load board preview')
        self.preview_load.Bind(wx.EVT_BUTTON, self._load_preview)
        action_icon(self.preview_load, wx.ART_FILE_OPEN)
        board_actions = wx.BoxSizer(wx.HORIZONTAL)
        board_actions.Add(self.preview_load, 0, wx.RIGHT, 8)
        self.focus_selected = action_icon(wx.Button(board_page, label='Focus selected'), wx.ART_FIND)
        self.focus_selected.Bind(wx.EVT_BUTTON, self._focus_selected)
        self.focus_selected.Disable()
        board_actions.Add(self.focus_selected, 0, wx.RIGHT, 8)
        fit_board = action_icon(wx.Button(board_page, label='Fit board'), wx.ART_GO_HOME)
        fit_board.Bind(wx.EVT_BUTTON, self._fit_board)
        board_actions.Add(fit_board)
        self.expand_view = wx.ToggleButton(board_page, label='Expand board')
        action_icon(self.expand_view, wx.ART_FIND)
        self.expand_view.Bind(wx.EVT_TOGGLEBUTTON, self._expand_board)
        board_actions.Add(self.expand_view, 0, wx.LEFT, 8)
        board_box.Add(board_actions, 0, wx.ALL, 8)
        selection_row = wx.BoxSizer(wx.HORIZONTAL)
        self.add_nets = wx.CheckBox(board_page, label='Add clicked nets to selection')
        selection_row.Add(self.add_nets, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        clear_nets = wx.Button(board_page, label='Clear net selection')
        clear_nets.Bind(wx.EVT_BUTTON, self._clear_nets)
        action_icon(clear_nets, wx.ART_DELETE)
        selection_row.Add(clear_nets)
        self.show_in_editor = action_icon(wx.Button(board_page, label='Show in PCB Editor'), wx.ART_GO_FORWARD)
        self.show_in_editor.SetToolTip('Explicitly select these nets in the originating PCB Editor. Saved hash and complete selection are checked; focus may be unavailable.')
        self.show_in_editor.Bind(wx.EVT_BUTTON, self._show_in_editor)
        self.show_in_editor.Disable()
        selection_row.Add(self.show_in_editor, 0, wx.LEFT, 8)
        board_box.Add(selection_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.selection = wx.StaticText(board_page, label='Click copper to select a net for your next request. Wheel: zoom. Drag: pan.')
        board_box.Add(self.selection, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        legend = wx.BoxSizer(wx.HORIZONTAL)
        for color, label in (('#087f98', 'Selected nets'), ('#758d86', 'Saved copper / pads'), ('#405d73', 'Board context')):
            swatch = wx.Panel(board_page, size=(12, 12)); swatch.SetBackgroundColour(color)
            legend.Add(swatch, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            legend.Add(wx.StaticText(board_page, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        board_box.Add(legend, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        from wayricad_runtime.preview import GeometryPreview
        self.preview = GeometryPreview(board_page, empty_text='Load a saved PCB preview when you need visual selection.', compact=True)
        self.preview.on_net_select = self._select_net
        board_box.Add(self.preview, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        board_page.SetSizer(board_box)
        self.tabs.AddPage(board_page, 'Board selection', imageId=2)
        body.Add(self.tabs, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.status = wx.StaticText(panel, label='Ready · local command planner')
        status_row = wx.BoxSizer(wx.HORIZONTAL)
        self.status_badge = wx.StaticText(panel, label='READY', style=wx.ALIGN_CENTER | wx.BORDER_SIMPLE)
        self.status_badge.SetForegroundColour('#087f7c')
        status_row.Add(self.status_badge, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        status_row.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.progress_gauge = wx.Gauge(panel, range=100, size=(150, 12))
        status_row.Add(self.progress_gauge, 0, wx.ALIGN_CENTER_VERTICAL)
        body.Add(status_row, 0, wx.EXPAND | wx.ALL, 12)
        self.progress_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._pulse_progress, self.progress_timer)
        panel.SetSizer(body)
        if board:
            self.set_board(board)
        self.Bind(wx.EVT_CLOSE, self._close)
        self.CentreOnScreen()

    def _engine(self):
        if self.engine is None:
            from wayricad_runtime import assistant
            self.engine = assistant
        return self.engine

    def _deliver(self, callback, *args):
        if not self.closed:
            wx.CallAfter(self._if_open, callback, *args)

    def _if_open(self, callback, *args):
        if not self.closed:
            callback(*args)

    def _set_busy(self, busy, message='Ready'):
        self.busy = busy
        self.ask.Enable(not busy)
        self.choose.Enable(not busy)
        self.query.Enable(not busy)
        self.run.Enable(not busy and bool(self.plan) and self.plan.get('status') == 'ready')
        self.cancel.Enable(busy)
        self.cancel.SetToolTip('Request cancellation of the running tool and retain its run record.')
        self.preview_load.Enable(not busy)
        self.choose_output.Enable(not busy)
        self.show_in_editor.Enable(not busy and bool(self.context.get('selected_nets')) and bool(self.board_sha256))
        self.status.SetLabel(message)
        self.status.SetToolTip(message)
        if busy:
            self._state('WORKING', '#996000')
            self.progress_timer.Start(90)
        else:
            self.progress_timer.Stop()
            self.progress_gauge.SetValue(0)
            self._state('READY', '#087f7c')

    def _state(self, label, color):
        self.status_badge.SetLabel(' ' + label + ' ')
        self.status_badge.SetForegroundColour(color)
        self.status_badge.GetParent().Layout()

    def _pulse_progress(self, event):
        if self.busy and not self.closed:
            self.progress_gauge.Pulse()

    def set_board(self, path):
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() != '.kicad_pcb':
            raise ValueError('Choose an existing saved .kicad_pcb file.')
        self.context = {'board': str(path)}
        for key, suffix in (('project', '.kicad_pro'), ('schematic', '.kicad_sch')):
            neighbor = path.with_suffix(suffix)
            if neighbor.is_file():
                self.context[key] = str(neighbor)
        self.board_path.ChangeValue(path.name)
        self.board_path.SetToolTip(str(path))
        self.loaded_board = None
        self.board_sha256 = None
        self._all_focus_points = []
        self._selection_targets = []
        self._generation += 1
        self.plan = None
        self.answers = {}
        self.run.Disable()
        self.focus_selected.Disable()
        self.show_in_editor.Disable()
        self.selection.SetLabel('Click copper to select a net for your next request.')
        self.preview.set_geometry()
        self.preview.context_lines = []; self.preview.context_pads = []
        self.preview.context_rings = []; self.preview.context_vias = []
        self.preview.footprint_lines = []; self.preview.references = []
        self.preview.focus_points = []; self.preview.net_targets = []
        self.preview.invalidate_scene(); self.preview.Refresh()

    def _choose(self, event):
        with wx.FileDialog(self, 'Choose saved PCB', wildcard='KiCad PCB (*.kicad_pcb)|*.kicad_pcb',
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.set_board(dialog.GetPath())

    def _example(self, event):
        index = self.examples.GetSelection() - 1
        if index >= 0:
            self.query.ChangeValue(EXAMPLES[index])

    def _ask(self, event=None, answers=None):
        if self.busy:
            return
        query = self.query.GetValue().strip()
        if not query:
            self.status.SetLabel('Type a request or choose an example.')
            return
        if answers is None:
            self.answers = {}
        else:
            self.answers.update(answers)
        self.plan = None
        self.cancel_event.clear()
        self._set_busy(True, 'Interpreting locally…')
        context = dict(self.context); current_answers = dict(self.answers)
        def work():
            try:
                result = self._engine().propose(query, context, current_answers)
                self._deliver(self._show_plan, result)
            except Exception as exc:
                self._deliver(self._error, str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _show_plan(self, plan):
        self.plan = plan
        self._set_busy(False, 'Plan: ' + plan.get('status', 'unknown').replace('_', ' '))
        state = plan.get('status', 'unknown')
        count = len(plan.get('steps', []))
        self.plan_summary.SetLabel(f'{count} check' + ('' if count == 1 else 's') + ' · ' + state.replace('_', ' '))
        self.plan_tasks.DeleteAllItems()
        for step in plan.get('steps', []):
            params = step.get('params', {})
            target = params.get('net') or params.get('nets') or params.get('refs') or params.get('board') or params.get('topology') or 'Inputs below'
            if isinstance(target, list):
                target = ', '.join(map(str, target))
            elif params.get('board') == target:
                target = Path(str(target)).name
            index = self.plan_tasks.InsertItem(self.plan_tasks.GetItemCount(), str(step.get('title', step.get('action', 'Check'))), 0 if state == 'ready' else 1)
            self.plan_tasks.SetItem(index, 1, str(target))
            self.plan_tasks.SetItem(index, 2, state.replace('_', ' '))
        self._state('READY' if state == 'ready' else 'INPUT NEEDED' if state == 'needs_input' else state.upper(),
                    '#087f7c' if state == 'ready' else '#996000')
        lines = [plan.get('query', ''), '', 'Interpretation']
        lines.extend('• ' + str(step.get('title', step.get('action', 'Check'))) for step in plan.get('steps', []))
        for step in plan.get('steps', []):
            if step.get('params'):
                lines.append('  Inputs: ' + ', '.join(f'{key}={value}' for key, value in step['params'].items()))
        lines.extend('\nAssumption: ' + str(value) for value in plan.get('assumptions', []))
        if plan.get('message'):
            lines.append('\n' + str(plan['message']))
        if plan.get('error'):
            lines.append('\nInput problem: ' + str(plan['error']))
        if plan.get('status') == 'unsupported':
            lines.append('\nThis request is outside the supported command catalogue. Try a narrower check or use the relevant plugin directly.')
        self.plan_text.ChangeValue('\n'.join(lines))
        self.question_sizer.Clear(delete_windows=True)
        self.question_controls = {}
        for question in plan.get('questions', []):
            row = wx.BoxSizer(wx.HORIZONTAL)
            label = question.get('label', question['key'])
            if question.get('unit'):
                label += ' (' + question['unit'] + ')'
            row.Add(wx.StaticText(self.questions, label=label), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            choices = question.get('choices') or (['true', 'false'] if question.get('kind') == 'boolean' else [])
            if choices:
                control = wx.ComboBox(self.questions, choices=[str(item.get('label', item.get('value', ''))) if isinstance(item, dict) else str(item) for item in choices],
                                      style=wx.CB_DROPDOWN)
                control._answer_choices = choices
            else:
                control = wx.TextCtrl(self.questions)
            control.SetToolTip(label)
            previous = self.answers.get(question['key'])
            if previous is not None:
                control.SetValue(str(previous))
            row.Add(control, 1, wx.EXPAND)
            self.question_controls[question['key']] = control
            self.question_sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)
            if question.get('error'):
                issue = wx.StaticText(self.questions, label=str(question['error']))
                issue.Wrap(600)
                issue.SetForegroundColour('#9b2c2c')
                control.SetToolTip(label + ': ' + str(question['error']))
                self.question_sizer.Add(issue, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        if self.question_controls:
            submit = wx.Button(self.questions, label='Use these inputs')
            submit.Bind(wx.EVT_BUTTON, self._answer)
            self.question_sizer.Add(submit, 0, wx.ALL, 4)
        for alternative in plan.get('alternatives', []):
            button = wx.Button(self.questions, label=str(alternative.get('title', alternative['action'])))
            button.Bind(wx.EVT_BUTTON, lambda event, action=alternative['action']: self._ask(answers={'action': action}))
            self.question_sizer.Add(button, 0, wx.EXPAND | wx.ALL, 4)
        self.questions.Show(bool(self.question_controls or plan.get('alternatives')))
        self.questions.Layout(); self.questions.SetupScrolling(scroll_x=False)
        self.tabs.GetPage(0).Layout()
        self.tabs.GetPage(0).SetupScrolling(scroll_x=False)
        self.tabs.SetSelection(0)
        if plan.get('status') == 'ready' and self.auto.GetValue() and not self.cancel_event.is_set():
            self._run()

    def _answer(self, event):
        answers = {}
        for key, control in self.question_controls.items():
            value = control.GetValue().strip()
            choices = getattr(control, '_answer_choices', [])
            index = control.GetSelection() if choices else -1
            if index >= 0 and isinstance(choices[index], dict):
                value = choices[index].get('value', value)
            if value != '':
                answers[key] = value
        self._ask(answers=answers)

    def _run(self, event=None):
        if self.busy or not self.plan or self.plan.get('status') != 'ready':
            return
        self.cancel_event.clear()
        self._set_busy(True, 'Running read-only check…')
        self.results.ChangeValue('Running…\n')
        self.report_list.Clear(); self.artifacts = []
        self.result_summary.SetLabel('Running · results and reports will appear here')
        self.tabs.SetSelection(1)
        plan = self.plan
        def work():
            try:
                result = self._engine().run_plan(plan, self.output_root, cancel=self.cancel_event,
                                                progress=lambda text: self._deliver(self._progress, text))
                self._deliver(self._show_result, result)
            except Exception as exc:
                self._deliver(self._error, str(exc))
        # Closing the last window must not abandon the broker before it kills
        # its subprocess and records cancellation. Window callbacks are gated
        # by ``closed``; this worker may finish safely after MainLoop returns.
        self.run_thread = threading.Thread(target=work, daemon=False)
        self.run_thread.start()

    def _progress(self, text):
        self.status.SetLabel(str(text))
        self.results.AppendText(str(text) + '\n')

    def _show_result(self, result):
        self._set_busy(False, 'Result: ' + str(result.get('status', 'complete')))
        import json
        summary = result.get('summary', '')
        self.results.AppendText('\n' + (summary if isinstance(summary, str) else json.dumps(summary, indent=2)) + '\n')
        for step in result.get('steps', []):
            self.results.AppendText(str(step.get('title', step.get('action', 'Check'))) + ': ' + str(step.get('status', 'complete')) + '\n')
            if step.get('error'):
                self.results.AppendText(str(step['error']) + '\n')
            for key in ('stdout', 'stderr'):
                if step.get(key):
                    text = str(step[key])
                    self.results.AppendText(text[:12000] + ('\n[Open the run record for the full output.]' if len(text) > 12000 else '') + '\n')
        result_root = Path(result.get('output_dir', self.output_root)).resolve()
        if not result_root.is_relative_to(self.output_root.resolve()):
            self._error('The returned results folder is outside the chosen output folder.')
            return
        self.artifacts = result.get('artifacts', [])
        self.result_root = result_root
        self.result_parent = self.output_root
        steps = result.get('steps', [])
        completed = sum(step.get('status') in {'completed', 'complete'} for step in steps)
        issues = sum(step.get('status') not in {'completed', 'complete'} for step in steps)
        self.result_summary.SetLabel(f'{completed} completed · {issues} unresolved · {len(self.artifacts)} files')
        self._state(str(result.get('status', 'complete')).replace('_', ' ').upper(),
                    '#087f7c' if result.get('status') in {'completed', 'complete'} else '#9b2c2c')
        self.report_list.Set([str(item.get('label', Path(item['path']).name)) for item in self.artifacts])
        if self.artifacts:
            self.report_list.SetSelection(0)
        # Most scientific workers write structured results rather than stdout.
        # Show their actual values in the window instead of only a success count.
        for artifact in self.artifacts:
            if Path(artifact.get('path', '')).name not in {'report.json', 'console-result.json'}:
                continue
            try:
                path = report_path(artifact, self.result_root)
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                document = json.loads(path.read_text(encoding='utf-8'))
                value = document.get('result', document) if isinstance(document, dict) else document
                text = json.dumps(value, indent=2, ensure_ascii=False)
                self.results.AppendText('\n' + artifact.get('label', path.name) + '\n' + text[:16000] + '\n')
                if len(text) > 16000:
                    self.results.AppendText('[Open the full report for the remaining data.]\n')
                self.results.ShowPosition(0)
                break
            except (OSError, ValueError, KeyError):
                continue

    def _open_report(self, event):
        index = self.report_list.GetSelection()
        if index == wx.NOT_FOUND:
            self.status.SetLabel('Select a report first.')
            return
        try:
            wx.LaunchDefaultBrowser(report_path(self.artifacts[index], self.result_root).as_uri())
        except (ValueError, OSError, KeyError) as exc:
            self.status.SetLabel(str(exc))

    def _choose_output(self, event):
        if self.busy:
            return
        with wx.DirDialog(self, 'Save Assistant results in', defaultPath=str(self.output_root),
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.output_root = Path(dialog.GetPath()).resolve()
                if not self.artifacts:
                    self.result_root = self.output_root
                    self.result_parent = self.output_root
                self.choose_output.SetToolTip(str(self.output_root))
                self.status.SetLabel('New results will be stored in ' + str(self.output_root))

    def _open_output(self, event):
        folder = self.result_root.resolve()
        if not folder.is_relative_to(self.result_parent.resolve()) or not folder.is_dir():
            self.status.SetLabel('Run a check first, or choose an existing results folder.')
            return
        wx.LaunchDefaultApplication(str(folder))

    def _cancel(self):
        self.cancel_event.set()
        self.status.SetLabel('Cancellation requested; waiting for the worker to stop…')
        self._state('CANCELLING', '#996000')

    def _error(self, message):
        self._set_busy(False, 'Check could not complete')
        self.results.AppendText('\n' + message + '\n')
        self._state('NEEDS ATTENTION', '#9b2c2c')
        self.tabs.SetSelection(1)

    def _load_preview(self, event=None):
        if self.busy:
            return
        if 'board' not in self.context:
            self.status.SetLabel('Choose a saved PCB first.')
            return
        if self.loaded_board is not None:
            self.preview.fit(None)
            return
        self._set_busy(True, 'Loading saved board preview…')
        path = self.context['board']; generation = self._generation
        def work():
            try:
                import pcbnew
                source_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                board = pcbnew.LoadBoard(path)
                if hashlib.sha256(Path(path).read_bytes()).hexdigest() != source_hash:
                    raise ValueError('The saved PCB changed while loading. Reload the preview.')
                self._deliver(self._show_board, generation, board, pcbnew, source_hash)
            except Exception as exc:
                self._deliver(self._error, str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _show_board(self, generation, board, api, source_hash=None):
        if generation != self._generation:
            return
        try:
            self.loaded_board = board
            self.preview.set_board(board, api)
            self.board_sha256 = source_hash or (hashlib.sha256(Path(self.context['board']).read_bytes()).hexdigest() if self.context.get('board') else None)
            self._all_focus_points = list(self.preview.focus_points)
            # The generic selector's centroid captions are not saved silkscreen.
            # Avoid fabricated labels and duplicate fab/courtyard outlines here.
            self.preview.references = []
            self.preview.footprint_lines = []
            self.preview.invalidate_scene(); self.preview.Refresh()
            self._set_busy(False, 'Board preview ready · click copper to choose a net')
        except Exception as exc:
            self.loaded_board = None
            self._error(str(exc))

    def _select_net(self, net, point):
        nets = list(self.context.get('selected_nets', [])) if self.add_nets.GetValue() else []
        if net not in nets:
            nets.append(net)
        self.context['selected_nets'] = nets
        caption = ', '.join(nets)
        self.selection.SetLabel('Selected: ' + (caption[:100] + '…' if len(caption) > 100 else caption))
        self.selection.SetToolTip(caption)
        targets = [item for item in self.preview.net_targets if item['net'] in nets]
        self._selection_targets = targets
        self.selection.SetLabel(f'{len(nets)} net' + ('' if len(nets) == 1 else 's') + f' · {len(targets)} copper targets · ' + (caption[:85] + '…' if len(caption) > 85 else caption))
        count = self.preview.set_highlight(nets=nets)
        self.selection.SetLabel(f'{len(nets)} net' + ('' if len(nets) == 1 else 's') + f' · {count} saved copper items · ' + (caption[:85] + '…' if len(caption) > 85 else caption))
        self.focus_selected.Enable(bool(count))
        self.show_in_editor.Enable(not self.busy and bool(self.board_sha256))
        self.plan = None
        self.run.Disable()

    def _clear_nets(self, event=None):
        self.context.pop('selected_nets', None)
        self.preview.set_highlight()
        self._selection_targets = []
        self.focus_selected.Disable()
        self.show_in_editor.Disable()
        self.selection.SetLabel('Click copper to select a net for your next request.')
        self.plan = None
        self.run.Disable()

    def _focus_selected(self, event=None):
        if not self.preview.focus_highlight():
            self.status.SetLabel('Select saved copper before focusing.')

    def _fit_board(self, event=None):
        if not self.preview.fit_board():
            self.status.SetLabel('Load a saved PCB before fitting the board.')

    def _expand_board(self, event=None):
        expanded = self.expand_view.GetValue()
        for item in list(self.body.GetChildren())[:7]:
            item.Show(not expanded)
        self.expand_view.SetLabel('Restore query' if expanded else 'Expand board')
        self.body.Layout()

    def _tab_changed(self, event):
        if event.GetSelection() != 2 and hasattr(self, 'expand_view') and self.expand_view.GetValue():
            self.expand_view.SetValue(False)
            self._expand_board()
        event.Skip()

    def _show_in_editor(self, event=None):
        if self.busy or not self.context.get('selected_nets') or not self.board_sha256:
            return
        path = self.context.get('board'); nets = list(self.context['selected_nets']); expected = self.board_sha256
        self._set_busy(True, 'Requesting selection in the originating PCB Editor…')
        self.cancel.Disable()
        self.cancel.SetToolTip('This selection request completes atomically; closing the window does not edit the design.')
        def work():
            try:
                from wayricad_runtime.analysis_selection import select_origin
                result = select_origin(path, nets=nets, expected_sha256=expected, focus=True, return_details=True)
                self._deliver(self._editor_selected, result)
            except Exception as exc:
                self._deliver(self._error, str(exc))
        threading.Thread(target=work, daemon=False).start()

    def _editor_selected(self, result):
        message = f'PCB Editor: {result.get("count", 0)} items selected · focus {result.get("focus", "unavailable")}'
        self._set_busy(False, message)
        self.results.AppendText('\n' + message + '\nSaved file matched; unsaved live geometry was not validated.\n')

    def _help(self, event):
        wx.LaunchDefaultBrowser((Path(__file__).parent / 'help.html').resolve().as_uri())

    def _close(self, event):
        self.closed = True
        self.cancel_event.set()
        self.progress_timer.Stop()
        self.Destroy()
