"""KiCad 10 menu registration must stay light and still launch the selected tool."""

import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import Mock, patch

from wayricad_runtime import legacy_menu


def _manifest(root, name="WayriCAD Constraint Studio", identifier="protocol-constraints"):
    (root / "plugin.json").write_text(json.dumps({
        "identifier": "com.github.wayri.wayricad." + identifier,
        "actions": [{"name": name, "description": "Open tool",
                     "icons-light": ["resources/icon-24.png"],
                     "icons-dark": ["resources/icon-dark-24.png"]}],
    }), encoding="utf-8")


def test_menu_registers_without_importing_tool_and_delegates_on_click(tmp_path):
    _manifest(tmp_path)
    (tmp_path / "wayricad-tool.json").write_text(json.dumps({
        "module": "action", "class": "Tool"}), encoding="utf-8")
    registered = []

    class FakeActionPlugin:
        def register(self):
            self.defaults()
            registered.append(self)

    wx = SimpleNamespace(GetApp=lambda: object(), MessageBox=Mock(), OK=1, ICON_ERROR=2)
    pcbnew = SimpleNamespace(ActionPlugin=FakeActionPlugin)
    delegate = Mock()
    with patch.dict(sys.modules, {"pcbnew": pcbnew, "wx": wx}), patch.object(
            legacy_menu.importlib, "import_module", return_value=SimpleNamespace(Tool=lambda: delegate)) as importer:
        legacy_menu.register("installed_wayricad", tmp_path)
        importer.assert_not_called()
        assert len(registered) == 1
        assert registered[0].name == "WayriCAD Constraint Studio"
        assert registered[0].show_toolbar_button is False
        registered[0].Run()
    importer.assert_called_once_with(".action", "installed_wayricad")
    delegate.Run.assert_called_once()


def test_headless_worker_does_not_register_menu(tmp_path):
    wx = SimpleNamespace(GetApp=lambda: None)
    pcbnew = SimpleNamespace(ActionPlugin=object)
    with patch.dict(sys.modules, {"pcbnew": pcbnew, "wx": wx}):
        legacy_menu.register("worker_package", tmp_path)


def test_copper_menu_never_executes_nested_registration_initializer(tmp_path, monkeypatch):
    _manifest(tmp_path, "WayriCAD Copper Balancer", "copper-balancer")
    nested = tmp_path / "copper_balancer"
    nested.mkdir()
    (nested / "__init__.py").write_text("raise RuntimeError('nested ActionPlugin registered')\n",
                                        encoding="utf-8")
    (nested / "plugin.py").write_text(
        "runs=0\nclass CopperBalancerPlugin:\n"
        "    def Run(self):\n"
        "        global runs\n"
        "        runs+=1\n", encoding="utf-8")
    registered = []

    class FakeActionPlugin:
        def register(self):
            self.defaults()
            registered.append(self)

    package = ModuleType("installed_copper")
    package.__path__ = [str(tmp_path)]
    wx = SimpleNamespace(GetApp=lambda: object(), MessageBox=Mock(), OK=1, ICON_ERROR=2)
    pcbnew = SimpleNamespace(ActionPlugin=FakeActionPlugin)
    for name, module in {"installed_copper": package, "pcbnew": pcbnew, "wx": wx}.items():
        monkeypatch.setitem(sys.modules, name, module)
    try:
        legacy_menu.register("installed_copper", tmp_path)
        assert len(registered) == 1
        registered[0].Run()
        registered[0].Run()
        module = sys.modules["installed_copper.copper_balancer.plugin"]
        assert module.runs == 2
    finally:
        for name in tuple(sys.modules):
            if name.startswith("installed_copper."):
                sys.modules.pop(name, None)
    assert len(registered) == 1
    wx.MessageBox.assert_not_called()


def test_bom_menu_launches_saved_project_without_ipc_socket(tmp_path):
    _manifest(tmp_path, "WayriCAD BOM Studio", "bom-studio")
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("board", encoding="utf-8")
    project = tmp_path / "demo.kicad_pro"
    project.write_text("{}", encoding="utf-8")
    (tmp_path / "desktop_entrypoint.py").write_text("", encoding="utf-8")
    actions = []

    class FakeActionPlugin:
        def register(self):
            self.defaults()
            actions.append(self)

    wx = SimpleNamespace(GetApp=lambda: object(), MessageBox=Mock(), OK=1, ICON_ERROR=2)
    pcbnew = SimpleNamespace(ActionPlugin=FakeActionPlugin,
                             GetBoard=lambda: SimpleNamespace(GetFileName=lambda: str(board)))
    with patch.dict(sys.modules, {"pcbnew": pcbnew, "wx": wx}), patch(
            "wayricad_runtime.runtime_setup.native_python", return_value=Path("python")), patch(
            "wayricad_runtime.runtime_setup.child_environment", return_value={}), patch.object(
            legacy_menu.subprocess, "Popen") as spawn:
        legacy_menu.register("installed_bom", tmp_path)
        assert actions[0].name == "WayriCAD — All tools…"
        next(action for action in actions if action.name == "WayriCAD BOM Studio").Run()
    assert str(project) in spawn.call_args.args[0]
    assert "KICAD_API_SOCKET" not in spawn.call_args.kwargs["env"]


def test_quick_pi_menu_passes_saved_board_without_ipc_socket(tmp_path):
    _manifest(tmp_path, "WayriCAD Quick PI", "quick-pi")
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("board", encoding="utf-8")
    (tmp_path / "desktop_entrypoint.py").write_text("", encoding="utf-8")
    actions = []

    class FakeActionPlugin:
        def register(self):
            self.defaults()
            actions.append(self)

    wx = SimpleNamespace(GetApp=lambda: object(), MessageBox=Mock(), OK=1, ICON_ERROR=2)
    pcbnew = SimpleNamespace(ActionPlugin=FakeActionPlugin,
                             GetBoard=lambda: SimpleNamespace(GetFileName=lambda: str(board)))
    with patch.dict(sys.modules, {"pcbnew": pcbnew, "wx": wx}), patch(
            "wayricad_runtime.runtime_setup.native_python", return_value=Path("python")), patch(
            "wayricad_runtime.runtime_setup.child_environment", return_value={}), patch.object(
            legacy_menu.subprocess, "Popen") as spawn:
        legacy_menu.register("installed_quick_pi", tmp_path)
        actions[-1].Run()
    assert spawn.call_args.args[0][-2:] == ["--board", str(board.resolve())]


def test_quick_pi_desktop_accepts_explicit_board_without_ipc(tmp_path):
    from quick_pi_plugin import desktop_entrypoint

    board = tmp_path / "demo.kicad_pcb"
    board.write_text("board", encoding="utf-8")
    with patch.object(sys, "argv", ["desktop_entrypoint.py", "--board", str(board)]), patch(
            "wayricad_runtime.bootstrap.relaunch", return_value=None), patch(
            "wayricad_runtime.native_analysis.active_saved_board") as active, patch(
            "wayricad_runtime.native_analysis.child_environment", return_value={}), patch.object(
            desktop_entrypoint.subprocess, "Popen") as spawn:
        spawn.return_value.wait.return_value = 0
        assert desktop_entrypoint.main() == 0
    active.assert_not_called()
    assert spawn.call_args.args[0][-3:] == ["--board", str(board.resolve()), "--ui"]
