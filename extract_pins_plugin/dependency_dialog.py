"""wxPython dependency manager for the complete KiWay suite."""

from __future__ import annotations

import subprocess
from typing import Any, List

import wx

from .dependency_manager import (
    health_report,
    install_command,
    install_dependencies,
    recommended_missing,
)


class DependencyManagerDialog(wx.Dialog):
    def __init__(self, parent: Any) -> None:
        super().__init__(
            parent,
            title="KiWay Suite Dependencies",
            size=(940, 720),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.dependency_rows: List[dict] = []
        self._build_ui()
        self.refresh(None)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(panel, label="KiWay Suite Dependency Manager")
        heading.SetFont(heading.GetFont().Bold().Larger())
        root.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        summary = wx.StaticText(
            panel,
            label="Checks the active KiCad Python environment and every installed KiWay package. Installations use KiCad's user-site and never modify Program Files.",
        )
        summary.Wrap(880)
        root.Add(summary, 0, wx.EXPAND | wx.ALL, 10)

        self.runtime = wx.StaticText(panel, label="")
        root.Add(self.runtime, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        dependencies_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="Python Dependencies"), wx.VERTICAL)
        self.dependencies = wx.ListCtrl(panel, style=wx.LC_REPORT)
        for index, (label, width) in enumerate(
            (("Install", 70), ("Dependency", 130), ("Status", 100), ("Version", 100), ("Level", 110), ("Features", 380))
        ):
            self.dependencies.InsertColumn(index, label, width=width)
        dependencies_box.Add(self.dependencies, 1, wx.EXPAND | wx.ALL, 6)
        root.Add(dependencies_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        suite_box = wx.StaticBoxSizer(wx.StaticBox(panel, label="KiWay Plugin Packages"), wx.VERTICAL)
        self.suite = wx.ListCtrl(panel, style=wx.LC_REPORT)
        for index, (label, width) in enumerate((("Plugin", 360), ("Status", 120), ("Version", 100), ("Package Folder", 260))):
            self.suite.InsertColumn(index, label, width=width)
        suite_box.Add(self.suite, 1, wx.EXPAND | wx.ALL, 6)
        root.Add(suite_box, 1, wx.EXPAND | wx.ALL, 10)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            ("Check Again", self.refresh),
            ("Install Recommended", self.install_recommended),
            ("Install Selected", self.install_selected),
            ("Copy Install Command", self.copy_command),
        ):
            button = wx.Button(panel, label=label)
            button.Bind(wx.EVT_BUTTON, handler)
            actions.Add(button, 0, wx.ALL, 4)
        close = wx.Button(panel, wx.ID_CLOSE, "Close")
        close.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CLOSE))
        actions.AddStretchSpacer(1)
        actions.Add(close, 0, wx.ALL, 4)
        root.Add(actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        self.status = wx.StaticText(panel, label="")
        self.status.Wrap(900)
        root.Add(self.status, 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(root)

    def refresh(self, _event: Any) -> None:
        report = health_report()
        runtime = report["runtime"]
        self.runtime.SetLabel(
            f"Python {runtime['python']} | {runtime['executable']}\n"
            f"User site: {runtime['user_site']} | pip: {'available' if runtime['pip_available'] else 'missing'}"
        )
        self.dependency_rows = report["dependencies"]
        self.dependencies.DeleteAllItems()
        for row in self.dependency_rows:
            selected = not row["satisfied"] and row["level"] in {"required", "recommended"}
            index = self.dependencies.InsertItem(self.dependencies.GetItemCount(), "Yes" if selected else "")
            for column, value in enumerate(
                (row["distribution"], row["status"], row["version"] or "-", row["level"], row["features"]),
                1,
            ):
                self.dependencies.SetItem(index, column, str(value))
            self.dependencies.SetItemData(index, index)
        self.suite.DeleteAllItems()
        for row in report["suite"]:
            index = self.suite.InsertItem(self.suite.GetItemCount(), row["name"])
            for column, value in enumerate((row["status"], row["version"] or "-", row["folder"]), 1):
                self.suite.SetItem(index, column, str(value))
        missing = [row["distribution"] for row in self.dependency_rows if not row["satisfied"]]
        self.status.SetLabel(
            "All required dependencies and plugin packages are available."
            if report["healthy"]
            else f"Review missing items. Missing Python dependencies: {', '.join(missing) or 'none'}."
        )

    def _selected_keys(self) -> List[str]:
        selected = []
        index = self.dependencies.GetFirstSelected()
        while index >= 0:
            if index < len(self.dependency_rows) and not self.dependency_rows[index]["satisfied"]:
                selected.append(self.dependency_rows[index]["key"])
            index = self.dependencies.GetNextSelected(index)
        return selected

    def install_recommended(self, _event: Any) -> None:
        self._install(recommended_missing())

    def install_selected(self, _event: Any) -> None:
        keys = self._selected_keys()
        if not keys:
            wx.MessageBox("Select one or more missing dependency rows first.", "KiWay Dependencies", wx.OK | wx.ICON_INFORMATION)
            return
        self._install(keys)

    def _install(self, keys: List[str]) -> None:
        if not keys:
            wx.MessageBox("All recommended dependencies are already installed.", "KiWay Dependencies", wx.OK | wx.ICON_INFORMATION)
            return
        command = subprocess.list2cmdline(install_command(keys))
        answer = wx.MessageBox(
            f"Install into KiCad's Python user-site?\n\n{command}",
            "Confirm Dependency Installation",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if answer != wx.YES:
            return
        with wx.BusyCursor():
            result = install_dependencies(keys)
        if result["returncode"]:
            details = result["stderr"] or result["stdout"] or "pip returned an error."
            wx.MessageBox(details[-4000:], "Dependency Installation Failed", wx.OK | wx.ICON_ERROR)
            return
        self.refresh(None)
        wx.MessageBox(
            "Dependencies installed successfully. Restart PCB Editor before using newly enabled features.",
            "KiWay Dependencies",
            wx.OK | wx.ICON_INFORMATION,
        )

    def copy_command(self, _event: Any) -> None:
        keys = self._selected_keys() or recommended_missing()
        if not keys:
            self.status.SetLabel("No missing recommended dependency needs an install command.")
            return
        command = subprocess.list2cmdline(install_command(keys))
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(command))
            wx.TheClipboard.Close()
            self.status.SetLabel("Install command copied to the clipboard.")
        else:
            self.status.SetLabel(command)
