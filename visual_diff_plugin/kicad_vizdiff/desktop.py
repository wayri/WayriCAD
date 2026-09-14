"""Small local launcher. Rendering runs outside the GUI process and cannot edit a board."""
from pathlib import Path
import os
import subprocess
import sys
import threading
import webbrowser

from .git import VizError, root
from .render import DEFAULT_LAYERS


def command_for(design, output, base="HEAD", head="WORKTREE", layers=DEFAULT_LAYERS,
                theme="", executable="", view=False, old_file=""):
    """Validate UI values independently of wx, preserving spaces and revision arguments."""
    design = Path(design).resolve()
    if not design.is_file() or design.suffix.lower() not in (".kicad_sch", ".kicad_pcb"):
        raise VizError("Choose an existing saved .kicad_sch or .kicad_pcb file.")
    repository = root(design.parent)
    output = Path(output).resolve()
    if output.suffix.lower() != ".html":
        raise VizError("Choose a report destination ending in .html.")
    if not head.strip() or (not view and not base.strip()):
        raise VizError("Enter revisions, such as HEAD and WORKTREE.")
    command = [sys.executable, "-m", __package__ + ".cli_runner", "view" if view else "diff",
               design.relative_to(repository).as_posix(), "--repo", str(repository),
               "--output", str(output), "--layers", layers]
    command += ["--ref", head.strip()] if view else ["--base", base.strip(), "--head", head.strip()]
    if old_file.strip() and not view:
        command += ["--old-file", old_file.strip()]
    if theme.strip():
        command += ["--theme", theme.strip()]
    if executable.strip():
        command += ["--kicad-cli", executable.strip()]
    return command, output


def show(initial_file=""):
    import wx

    class Window(wx.Frame):
        def __init__(self):
            super().__init__(None, title="WayriCAD Visual Diff", size=(680, 500))
            self.process = None
            self.report = None
            self.closed = False
            panel = wx.Panel(self)
            layout = wx.BoxSizer(wx.VERTICAL)
            title = wx.StaticText(panel, label="Compare saved design revisions")
            title.SetFont(title.GetFont().Bold().Larger())
            layout.Add(title, 0, wx.ALL, 16)
            hint = wx.StaticText(panel, label="Choose a PCB or root schematic in a Git repository. Save editor changes first.")
            hint.Wrap(620)
            layout.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
            form = wx.FlexGridSizer(cols=2, hgap=12, vgap=10)
            form.AddGrowableCol(1)
            self.design = wx.FilePickerCtrl(panel, path=initial_file,
                wildcard="KiCad designs (*.kicad_pcb;*.kicad_sch)|*.kicad_pcb;*.kicad_sch",
                style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL)
            self.mode = wx.Choice(panel, choices=["Compare revisions", "View one revision"])
            self.mode.SetSelection(0)
            self.base = wx.TextCtrl(panel, value="HEAD")
            self.head = wx.TextCtrl(panel, value="WORKTREE")
            self.output = wx.FilePickerCtrl(panel, wildcard="Local HTML report (*.html)|*.html",
                style=wx.FLP_SAVE | wx.FLP_USE_TEXTCTRL)
            self.base_label = None
            for label, field in (("Design", self.design), ("Review", self.mode),
                                 ("Base", self.base), ("Head", self.head), ("Report", self.output)):
                text = wx.StaticText(panel, label=label)
                if label == "Base": self.base_label = text
                form.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
                form.Add(field, 1, wx.EXPAND)
            layout.Add(form, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)
            self.options = wx.CollapsiblePane(panel, label="Rendering options", style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE)
            option_panel = self.options.GetPane()
            option_form = wx.FlexGridSizer(cols=2, hgap=12, vgap=8)
            option_form.AddGrowableCol(1)
            self.layers = wx.TextCtrl(option_panel, value=DEFAULT_LAYERS)
            self.theme = wx.TextCtrl(option_panel)
            self.old_file = wx.TextCtrl(option_panel)
            self.executable = wx.FilePickerCtrl(option_panel, style=wx.FLP_OPEN | wx.FLP_USE_TEXTCTRL)
            for label, field in (("PCB layers", self.layers), ("KiCad theme", self.theme),
                                 ("Previous path", self.old_file), ("KiCad CLI (optional)", self.executable)):
                option_form.Add(wx.StaticText(option_panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                option_form.Add(field, 1, wx.EXPAND)
            option_panel.SetSizer(option_form)
            layout.Add(self.options, 0, wx.EXPAND | wx.ALL, 16)
            self.status = wx.StaticText(panel, label="Ready. Reports contain all assets and make no network requests.")
            self.status.Wrap(620)
            layout.Add(self.status, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)
            buttons = wx.BoxSizer(wx.HORIZONTAL)
            help_button = wx.Button(panel, label="Help")
            help_button.Bind(wx.EVT_BUTTON, lambda event: webbrowser.open((Path(__file__).resolve().parents[1] / "help.html").as_uri()))
            buttons.Add(help_button, 0)
            self.open = wx.Button(panel, label="Open report")
            self.open.Disable()
            self.render = wx.Button(panel, label="Create report")
            self.render.SetDefault()
            buttons.AddStretchSpacer()
            buttons.Add(self.open, 0, wx.RIGHT, 8)
            buttons.Add(self.render, 0)
            layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 16)
            panel.SetSizer(layout)
            self.options.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, lambda event: (self.SetSize((680, 680 if not self.options.IsCollapsed() else 500)), panel.Layout()))
            self.design.Bind(wx.EVT_FILEPICKER_CHANGED, self.choose)
            self.mode.Bind(wx.EVT_CHOICE, self.change_mode)
            self.render.Bind(wx.EVT_BUTTON, self.start)
            self.open.Bind(wx.EVT_BUTTON, lambda event: webbrowser.open(self.report.as_uri()))
            self.Bind(wx.EVT_CLOSE, self.close)
            if initial_file: self.choose(None)
            self.SetMinSize((620, 470))
            self.Centre()

        def choose(self, event):
            design = Path(self.design.GetPath())
            if design.is_file():
                self.output.SetPath(str(design.parent / ".wayricad-visual-diff" / (design.stem + ".html")))

        def change_mode(self, event):
            enabled = self.mode.GetSelection() == 0
            self.base.Enable(enabled)
            self.base_label.Enable(enabled)
            self.old_file.Enable(enabled)

        def start(self, event):
            try:
                command, report = command_for(self.design.GetPath(), self.output.GetPath(), self.base.GetValue(),
                    self.head.GetValue(), self.layers.GetValue(), self.theme.GetValue(), self.executable.GetPath(),
                    self.mode.GetSelection() == 1, self.old_file.GetValue())
                environment = os.environ.copy()
                # Support both the standalone PCM package and repository imports.
                package_root = Path(__file__).resolve().parents[len(__package__.split("."))]
                environment["PYTHONPATH"] = str(package_root) + os.pathsep + environment.get("PYTHONPATH", "")
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except (VizError, OSError, ValueError) as exc:
                self.status.SetLabel(str(exc)); return
            self.render.Disable(); self.open.Disable()
            self.status.SetLabel("Rendering saved revisionsâ€¦ You can cancel without changing your design.")
            process = self.process

            def wait():
                result, _ = process.communicate()
                wx.CallAfter(self.finished, process, report, result)
            threading.Thread(target=wait, daemon=True).start()

        def finished(self, process, report, result):
            if self.closed: return
            self.process = None
            self.render.Enable()
            if process.returncode == 0 and report.is_file():
                self.report = report; self.open.Enable()
                self.status.SetLabel("Report ready. Open it to compare layers and sheets, overlay, swipe or inspect changes.")
                webbrowser.open(report.as_uri())
            else:
                message = "Render cancelled." if process.returncode and process.returncode < 0 else (result.strip().splitlines()[-1] if result.strip() else "Rendering did not complete.")
                self.status.SetLabel(message)
            self.status.Wrap(620)

        def close(self, event):
            if self.process and self.process.poll() is None and event.CanVeto():
                self.status.SetLabel("Rendering is still running. This window will remain available until it finishes.")
                event.Veto()
                return
            self.closed = True
            self.Destroy()

    window = Window()
    window.Show()
    return window


def main():
    import wx
    app = wx.App.Get() or wx.App(False)
    initial = ""
    try:
        # Only discover the saved board path. No legacy API emulation or mutations.
        from kipy import KiCad
        board = KiCad(timeout_ms=1500).get_board()
        name = Path(board.name)
        initial = str(name if name.is_absolute() else Path(board.get_project().path) / name)
    except Exception:
        pass  # Explicit file selection remains available with no IPC connection.
    show(initial)
    app.MainLoop()
    return 0
