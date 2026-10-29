"""Small KiCad 10 ActionPlugin menu bridge for independently installed IPC tools.

KiCad 10 places IPC actions on the toolbar, while Tools > External Plugins only
shows SWIG ActionPlugins.  Keep this registration light: importing a full tool
while KiCad scans plugins can fail before any user has chosen to run it.
"""

import importlib
import json
from pathlib import Path
import subprocess
import sys
import traceback
import types


_NATIVE_ACTIONS = {
    "copper-balancer": ("copper_balancer.plugin", "CopperBalancerPlugin"),
    "mechanical-check": ("plugin", "MechanicalCheckPlugin"),
}
MENU_ACTIONS = {}


def _choose_tool(root=None):
    """Keep every installed tool reachable even when KiCad's menu is taller than the screen."""
    import wx

    actions = dict(MENU_ACTIONS)
    if root is not None:
        from .tool_picker import installed_desktop_tools

        class InstalledTool:
            def __init__(self, name, location, identifier):
                self.name, self.location, self.identifier = name, location, identifier

            def Run(self):
                import pcbnew
                _launch_desktop(self.location, self.identifier, pcbnew, self.name)

        for name, (location, identifier) in installed_desktop_tools(root).items():
            actions.setdefault(name, InstalledTool(name, location, identifier))
    dialog = wx.Dialog(None, title="WayriCAD — All tools", size=(540, 480),
                       style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    dialog.SetMinSize((360, 300))
    panel = wx.Panel(dialog)
    layout = wx.BoxSizer(wx.VERTICAL)
    layout.Add(wx.StaticText(panel, label="Search installed WayriCAD tools"), 0, wx.ALL, 10)
    search = wx.SearchCtrl(panel)
    layout.Add(search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
    from .tool_picker import create_tool_list
    choices = create_tool_list(panel)
    layout.Add(choices, 1, wx.EXPAND | wx.ALL, 10)
    buttons = wx.StdDialogButtonSizer()
    open_button = wx.Button(panel, wx.ID_OK, "Open")
    open_button.SetDefault()
    buttons.AddButton(open_button)
    buttons.AddButton(wx.Button(panel, wx.ID_CANCEL, "Cancel"))
    buttons.Realize()
    layout.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 10)
    panel.SetSizer(layout)
    outer = wx.BoxSizer(wx.VERTICAL)
    outer.Add(panel, 1, wx.EXPAND)
    dialog.SetSizer(outer)
    selected = [None]

    def refresh(_event=None):
        query = search.GetValue().strip().casefold()
        names = [name for name in sorted(actions) if query in name.casefold()]
        choices.Set(names)
        if names:
            choices.SetSelection(0)
        open_button.Enable(bool(names))

    def choose(_event):
        selected[0] = choices.GetStringSelection()
        if selected[0]:
            dialog.EndModal(wx.ID_OK)

    search.Bind(wx.EVT_TEXT, refresh)
    choices.Bind(wx.EVT_LEFT_DCLICK, choose)
    open_button.Bind(wx.EVT_BUTTON, choose)
    refresh()
    search.SetFocus()
    try:
        if dialog.ShowModal() == wx.ID_OK and selected[0] in actions:
            return actions[selected[0]]
        return None
    finally:
        dialog.Destroy()


def _saved_board(pcbnew, title):
    import wx

    board = pcbnew.GetBoard()
    name = board.GetFileName() if board is not None else ""
    path = Path(name) if name else None
    if path is None or not path.is_file():
        wx.MessageBox("Open and save a PCB before launching this tool.", title,
                      wx.OK | wx.ICON_INFORMATION)
        return None
    return path.resolve()


def _launch_desktop(root, identifier, pcbnew, title):
    board = _saved_board(pcbnew, title)
    if board is None:
        return
    script = root / "desktop_entrypoint.py"
    from wayricad_runtime.runtime_setup import native_python, child_environment

    args = [str(native_python()), "-I", str(script)]
    if identifier == "bom-studio":
        project = board.with_suffix(".kicad_pro")
        schematic = board.with_suffix(".kicad_sch")
        source = project if project.is_file() else schematic
        if not source.is_file():source=board
        args.append(str(source))
    elif identifier in {"quick-pi", "quick-therm", "quick-emerge", "assistant", "review-comments"}:
        args.extend(("--board", str(board)))
    subprocess.Popen(args, env=child_environment(),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def register(package_name, root):
    """Register one menu entry without importing tool code during KiCad startup."""
    try:
        import pcbnew
        import wx
    except ImportError:
        # The same package initializer is loaded by standalone CLI workers.
        return

    if wx.GetApp() is None or not hasattr(pcbnew, "ActionPlugin"):
        return
    root = Path(root).resolve()
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    action = manifest["actions"][0]
    identifier = manifest["identifier"].rsplit(".", 1)[-1]
    config_path = root / "wayricad-tool.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None

    if identifier == "bom-studio":
        class SuiteMenu(pcbnew.ActionPlugin):
            def defaults(self):
                self.name = "WayriCAD — All tools…"
                self.category = "WayriCAD"
                self.description = "Search and open installed WayriCAD tools."
                self.show_toolbar_button = False
                self.icon_file_name = str(root / action["icons-light"][0])

            def Run(self):
                chosen = _choose_tool(root)
                if chosen is not None:
                    chosen.Run()

        SuiteMenu().register()

    class MenuAction(pcbnew.ActionPlugin):
        def defaults(self):
            self.name = action["name"]
            self.category = "WayriCAD"
            self.description = action.get("description", manifest.get("description", ""))
            self.show_toolbar_button = True
            self.icon_file_name = str(root / action["icons-light"][0])
            self.dark_icon_file_name = str(root / action["icons-dark"][0])

        def Run(self):
            loading = None
            try:
                if identifier in {"bom-studio", "quick-pi", "quick-therm", "quick-emerge", "assistant", "review-comments"}:
                    _launch_desktop(root, identifier, pcbnew, self.name)
                    return
                from .loading import LoadingWindow
                loading = LoadingWindow(self.name)
                module_name, class_name = (
                    (config["module"], config["class"]) if config is not None
                    else _NATIVE_ACTIONS[identifier]
                )
                if identifier == "copper-balancer":
                    # Its nested source initializer auto-registers another
                    # ActionPlugin when imported inside PCB Editor. Provide a
                    # package path for .plugin/.dialog without executing it.
                    nested_name = package_name + ".copper_balancer"
                    if nested_name not in sys.modules:
                        nested = types.ModuleType(nested_name)
                        nested.__package__ = nested_name
                        nested.__path__ = [str(root / "copper_balancer")]
                        sys.modules[nested_name] = nested
                module = importlib.import_module("." + module_name, package_name)
                self._delegate = getattr(module, class_name)()
                from .launcher import _finish_loading_on_window
                finish_loading = _finish_loading_on_window(wx, loading, None)
                self._delegate.Run()
                finish_loading()
            except Exception as exc:
                print(traceback.format_exc(), file=sys.stderr)
                wx.MessageBox(str(exc), self.name, wx.OK | wx.ICON_ERROR)
            finally:
                if loading is not None:
                    loading.finish()

    menu_action = MenuAction()
    menu_action.register()
    MENU_ACTIONS[action["name"]] = menu_action
