"""Native preflight and export window."""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path

import wx
try:
    import wx.html2 as webview
except ImportError:
    webview = None

from .exporter import (
    ExportSelection,
    assert_scan_current,
    estimate_export_size,
    load_viewer_assets,
    scan_project,
    viewer_asset_dir,
    write_export_document,
)


def _format_bytes(value: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value} B"
        value /= 1024
    return f"{value:.1f} GiB"


class PortableWebExportFrame(wx.Frame):
    def __init__(self, parent, board_path: str):
        super().__init__(parent, title="WayriCAD Portable Web Export", size=(1050, 760))
        self.package_root = Path(__file__).resolve().parent
        self.scan = None
        self.preview_current = False
        self.preview_document: str | None = None
        self.preview_manifest: dict | None = None
        self.sheet_paths: list[Path] = []
        self.model_sources: list[str] = []
        self._build()
        self.load_project(board_path)

    def _build(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)
        heading = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(panel, label="Portable Web Export")
        title.SetFont(title.GetFont().Bold())
        heading.Add(title, 0, wx.ALIGN_CENTER_VERTICAL)
        self.summary = wx.StaticText(panel, label="Select content, review diagnostics and export one offline HTML file.")
        self.summary.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        heading.Add(self.summary, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 14)
        help_button = wx.Button(panel, label="Help")
        help_button.Bind(wx.EVT_BUTTON, self._help)
        heading.Add(help_button, 0)
        outer.Add(heading, 0, wx.EXPAND | wx.ALL, 12)
        outer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        source_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Project source")
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        self.board_text = wx.TextCtrl(panel, style=wx.TE_READONLY)
        source_row.Add(self.board_text, 1, wx.EXPAND)
        refresh = wx.Button(panel, label="Rescan")
        refresh.Bind(wx.EVT_BUTTON, lambda _event: self.load_project(self.board_text.GetValue()))
        source_row.Add(refresh, 0, wx.LEFT, 8)
        source_box.Add(source_row, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(source_box, 0, wx.EXPAND | wx.ALL, 10)

        content = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(content)
        right = wx.Panel(content)
        content.SplitVertically(left, right, 510)
        content.SetMinimumPaneSize(300)
        left_layout = wx.BoxSizer(wx.VERTICAL)
        views = wx.StaticBoxSizer(wx.VERTICAL, left, "Views and design data")
        self.include_schematic = wx.CheckBox(left, label="Schematic")
        self.include_pcb = wx.CheckBox(left, label="PCB Layout")
        self.include_bom = wx.CheckBox(left, label="BoM and assembly/procurement tracking")
        self.include_3d = wx.CheckBox(left, label="3D board and selected supported models")
        for control in (self.include_schematic, self.include_pcb, self.include_bom, self.include_3d):
            control.SetValue(True)
            control.Bind(wx.EVT_CHECKBOX, self._selection_changed)
            views.Add(control, 0, wx.ALL, 4)
        left_layout.Add(views, 0, wx.EXPAND | wx.ALL, 8)

        sheets_box = wx.StaticBoxSizer(wx.VERTICAL, left, "Schematic sheets")
        self.sheets = wx.CheckListBox(left)
        self.sheets.Bind(wx.EVT_CHECKLISTBOX, self._selection_changed)
        sheets_box.Add(self.sheets, 1, wx.EXPAND | wx.ALL, 6)
        left_layout.Add(sheets_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        models_box = wx.StaticBoxSizer(wx.VERTICAL, left, "Available 3D models")
        self.models = wx.CheckListBox(left)
        self.models.Bind(wx.EVT_CHECKLISTBOX, self._selection_changed)
        models_box.Add(self.models, 1, wx.EXPAND | wx.ALL, 6)
        left_layout.Add(models_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        left.SetSizer(left_layout)

        right_layout = wx.BoxSizer(wx.VERTICAL)
        self.review_tabs = wx.Notebook(right)
        preflight_page = wx.Panel(self.review_tabs)
        preview_page = wx.Panel(self.review_tabs)
        self.review_tabs.AddPage(preflight_page, "Preflight")
        self.review_tabs.AddPage(preview_page, "Web page preview")
        preflight_layout = wx.BoxSizer(wx.VERTICAL)
        diagnostics = wx.StaticBoxSizer(wx.VERTICAL, preflight_page, "Missing, unsupported and included assets")
        self.preflight = wx.ListCtrl(preflight_page, style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES)
        self.preflight.InsertColumn(0, "Severity", width=90)
        self.preflight.InsertColumn(1, "Item", width=430)
        diagnostics.Add(self.preflight, 1, wx.EXPAND | wx.ALL, 6)
        preflight_layout.Add(diagnostics, 1, wx.EXPAND | wx.ALL, 8)

        estimate = wx.StaticBoxSizer(wx.VERTICAL, preflight_page, "Export estimate and traceability")
        self.estimate = wx.StaticText(preflight_page, label="Not scanned")
        self.estimate.SetFont(self.estimate.GetFont().Bold())
        self.storage_note = wx.StaticText(preflight_page, label="")
        self.storage_note.Wrap(430)
        estimate.Add(self.estimate, 0, wx.ALL, 8)
        estimate.Add(self.storage_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        preflight_layout.Add(estimate, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        preview_actions = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button = wx.Button(preflight_page, label="Build Exact Web Preview")
        self.preview_button.SetToolTip("Render the exact selected self-contained HTML inside this window before export")
        self.preview_button.Bind(wx.EVT_BUTTON, self._preview)
        preview_actions.Add(self.preview_button, 0)
        self.preview_note = wx.StaticText(preflight_page, label="The preview is regenerated on demand after selection changes.")
        preview_actions.Add(self.preview_note, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        preflight_layout.Add(preview_actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        preflight_page.SetSizer(preflight_layout)

        preview_layout = wx.BoxSizer(wx.VERTICAL)
        if webview is not None:
            self.web_preview = webview.WebView.New(preview_page)
            preview_layout.Add(self.web_preview, 1, wx.EXPAND)
        else:
            self.web_preview = None
            preview_layout.Add(wx.StaticText(preview_page, label="wx.html2 WebView is unavailable in this Python runtime."), 1, wx.ALL, 12)
        preview_page.SetSizer(preview_layout)
        right_layout.Add(self.review_tabs, 1, wx.EXPAND)
        right.SetSizer(right_layout)
        outer.Add(content, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        destination_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Output")
        self.destination = wx.FilePickerCtrl(
            panel,
            message="Save portable HTML",
            wildcard="HTML files (*.html)|*.html",
            style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT | wx.FLP_USE_TEXTCTRL,
        )
        destination_box.Add(self.destination, 0, wx.EXPAND | wx.ALL, 8)
        outer.Add(destination_box, 0, wx.EXPAND | wx.ALL, 10)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.status = wx.StaticText(panel, label="")
        actions.Add(self.status, 1, wx.ALIGN_CENTER_VERTICAL)
        close = wx.Button(panel, wx.ID_CLOSE, "Close")
        close.Bind(wx.EVT_BUTTON, lambda _event: self.Close())
        actions.Add(close, 0, wx.RIGHT, 8)
        self.export_button = wx.Button(panel, label="Export Reviewed HTML")
        self.export_button.SetDefault()
        self.export_button.Bind(wx.EVT_BUTTON, self._export)
        actions.Add(self.export_button, 0)
        outer.Add(actions, 0, wx.EXPAND | wx.ALL, 12)
        panel.SetSizer(outer)

    def load_project(self, board_path: str):
        if not board_path:
            return
        self.board_text.SetValue(str(board_path))
        try:
            self.scan = scan_project(board_path)
        except Exception as exc:
            wx.MessageBox(str(exc), "Portable Web Export", wx.OK | wx.ICON_ERROR)
            return
        self._invalidate_preview("Project rescanned; build a new exact preview before export.")
        self.sheet_paths = list(self.scan.schematics)
        self.sheets.Set([str(path.relative_to(self.scan.project_root)) for path in self.sheet_paths])
        for index in range(len(self.sheet_paths)):
            self.sheets.Check(index, True)
        supported = [model for model in self.scan.models if model.supported]
        self.model_sources = [model.source for model in supported]
        self.models.Set([model.source for model in supported])
        for index in range(len(supported)):
            self.models.Check(index, True)
        self.destination.SetPath(str(self.scan.project_root / f"{self.scan.board.stem}-interactive-review.html"))
        self._refresh_preflight()

    def _selection(self) -> ExportSelection:
        sheets = tuple(path for index, path in enumerate(self.sheet_paths) if self.sheets.IsChecked(index))
        models = tuple(source for index, source in enumerate(self.model_sources) if self.models.IsChecked(index))
        return ExportSelection(
            include_schematic=self.include_schematic.GetValue(),
            include_pcb=self.include_pcb.GetValue(),
            include_bom=self.include_bom.GetValue(),
            include_3d=self.include_3d.GetValue(),
            schematic_paths=sheets,
            model_sources=models,
        )

    def _selection_changed(self, event):
        self._invalidate_preview("Selection changed; rebuild the exact preview before export.")
        if self.review_tabs.GetSelection() == 1:
            self.review_tabs.SetSelection(0)
        self._refresh_preflight()
        event.Skip()

    def _invalidate_preview(self, message: str) -> None:
        self.preview_current = False
        self.preview_document = None
        self.preview_manifest = None
        if hasattr(self, "preview_note"):
            self.preview_note.SetLabel(message)

    def _refresh_preflight(self):
        self.preflight.DeleteAllItems()
        if self.scan is None:
            return
        findings = [("Warning", issue) for issue in self.scan.issues]
        if self.include_schematic.GetValue() and not any(self.sheets.IsChecked(i) for i in range(self.sheets.GetCount())):
            findings.append(("Error", "Schematic is enabled but no sheets are selected."))
        if not any(control.GetValue() for control in
                   (self.include_schematic, self.include_pcb, self.include_bom, self.include_3d)):
            findings.append(("Error", "Select at least one view or the BoM."))
        if self.include_3d.GetValue() and not self.include_pcb.GetValue():
            findings.append(("Info", "The saved PCB is included internally because the 3D view requires it."))
        try:
            script, _notices = load_viewer_assets(self.package_root)
            viewer_bytes = len(script.encode("utf-8"))
            findings.append(("Ready", f"KiCad WebView {viewer_asset_dir(self.package_root)}"))
        except Exception as exc:
            viewer_bytes = 0
            findings.append(("Error", str(exc)))
        for severity, item in findings:
            row = self.preflight.InsertItem(self.preflight.GetItemCount(), severity)
            self.preflight.SetItem(row, 1, item)
        estimate = estimate_export_size(self.scan, self._selection(), viewer_bytes)
        self.estimate.SetLabel(f"Expected HTML size: approximately {_format_bytes(estimate)}")
        self.storage_note.SetLabel(
            f"{len(self.scan.components)} component references · {len(self.sheet_paths)} sheets · "
            f"{len(self.model_sources)} supported models. Tracking is saved in browser local storage "
            "for this project/revision and can be exported as JSON; it does not modify the HTML file."
        )
        has_error = any(self.preflight.GetItemText(i) == "Error" for i in range(self.preflight.GetItemCount()))
        self.export_button.Enable(not has_error and self.preview_current)
        self.preview_button.Enable(not has_error and self.web_preview is not None)
        if not has_error and not self.preview_current:
            self.status.SetLabel("Build and review the embedded web preview before export.")

    def _preview(self, _event):
        from .exporter import build_export

        self.preview_button.Disable()
        self.status.SetLabel("Building the exact offline page preview…")
        wx.YieldIfNeeded()
        try:
            document, manifest = build_export(self.scan, self._selection(), self.package_root)
            self.web_preview.SetPage(document, "file:///")
            self.review_tabs.SetSelection(1)
            self.preview_document = document
            self.preview_manifest = manifest
            self.preview_current = True
            self.preview_note.SetLabel("Preview matches the current selection.")
            self.status.SetLabel(
                f"Previewing document {manifest['documentId']} · revision {manifest['revisionId']} · {manifest['generatedAt']}"
            )
            self._refresh_preflight()
        except Exception as exc:
            wx.MessageBox(str(exc), "Portable Web Export preview failed", wx.OK | wx.ICON_ERROR)
            self.status.SetLabel("Preview failed; no project file was changed.")
        finally:
            self.preview_button.Enable()

    def _export(self, _event):
        if not self.preview_current or self.preview_document is None or self.preview_manifest is None:
            wx.MessageBox(
                "Build and review the current web preview before exporting.",
                "Portable Web Export",
                wx.OK | wx.ICON_INFORMATION,
            )
            return
        destination = Path(self.destination.GetPath())
        if destination.suffix.casefold() not in {".html", ".htm"}:
            destination = destination.with_suffix(".html")
            self.destination.SetPath(str(destination))
        self.export_button.Disable()
        self.status.SetLabel("Writing the exact reviewed HTML…")
        wx.YieldIfNeeded()
        try:
            assert_scan_current(self.scan)
            if not self.preview_current or self.preview_document is None:
                raise ValueError("Preview is stale; rebuild before export.")
            write_export_document(self.preview_document, destination,
                                  protected_sources=self.scan.source_hashes)
            manifest = self.preview_manifest
        except Exception as exc:
            wx.MessageBox(str(exc), "Portable Web Export failed", wx.OK | wx.ICON_ERROR)
            self.status.SetLabel("Export failed; no design file was changed.")
        else:
            self.status.SetLabel(f"Exported revision {manifest['revisionId']} to {destination.name}")
            dialog = wx.MessageDialog(
                self,
                "The offline HTML was created. Open it in a supported browser and review every selected tab, model and component link before distribution.\n\nOpen it now?",
                "Portable Web Export complete",
                wx.YES_NO | wx.ICON_INFORMATION,
            )
            try:
                if dialog.ShowModal() == wx.ID_YES:
                    webbrowser.open(destination.as_uri())
            finally:
                dialog.Destroy()
        finally:
            self._refresh_preflight()

    def _help(self, _event):
        webbrowser.open((self.package_root / "help.html").as_uri())
