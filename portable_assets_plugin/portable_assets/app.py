from __future__ import annotations

import threading
import traceback
import webbrowser
from pathlib import Path

import wx
import wx.dataview as dv

from .core.engine import (
    ProjectContext,
    PortableOptions,
    make_portable,
    missing_footprints,
    repair_missing_footprints,
    restore_from_vault,
    scan_project,
    project_signature,
)


class PortableAssetsFrame(wx.Frame):
    def __init__(self, ctx: ProjectContext):
        super().__init__(None, title="WayriCAD Portable Assets", size=(1080, 760))
        self.ctx = ctx
        self.SetMinSize((920, 640))
        self._busy = False
        self._report = None
        self._analysis_signature = None
        self._build_ui()
        self.Centre()
        wx.CallAfter(self.run_analysis)

    def _build_ui(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        header = wx.BoxSizer(wx.HORIZONTAL)
        title_box = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(panel, label="Portable Assets")
        font = title.GetFont()
        font.SetPointSize(font.GetPointSize() + 6)
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(font)
        subtitle = wx.StaticText(panel, label="Make a KiCad project self-contained without losing its native library links.")
        title_box.Add(title, 0, wx.BOTTOM, 2)
        title_box.Add(subtitle, 0)
        header.Add(title_box, 1, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 14)
        self.project_label = wx.StaticText(panel, label=str(self.ctx.project_dir))
        header.Add(self.project_label, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 14)
        help_button = wx.Button(panel, label="Help")
        help_button.SetToolTip("Open the bundled workflow, safeguards, examples, and troubleshooting guide.")
        help_button.Bind(wx.EVT_BUTTON, self.open_help)
        header.Add(help_button, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 14)
        outer.Add(header, 0, wx.EXPAND)
        outer.Add(wx.StaticLine(panel), 0, wx.EXPAND)

        self.notebook = wx.Notebook(panel)
        self.tab_portable = wx.Panel(self.notebook)
        self.tab_assets = wx.Panel(self.notebook)
        self.tab_vault = wx.Panel(self.notebook)
        self.tab_repair = wx.Panel(self.notebook)  # deliberately last tab
        self.notebook.AddPage(self.tab_portable, "Make Portable")
        self.notebook.AddPage(self.tab_assets, "Assets")
        self.notebook.AddPage(self.tab_vault, "Embedded Vault")
        self.notebook.AddPage(self.tab_repair, "Repair Missing Footprints")
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)

        self._build_portable_tab()
        self._build_assets_tab()
        self._build_vault_tab()
        self._build_repair_tab()

        footer = wx.BoxSizer(wx.VERTICAL)
        self.progress = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL)
        self.status = wx.StaticText(panel, label="Ready")
        self.log = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2, size=(-1, 92))
        footer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        footer.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        footer.Add(self.log, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(footer, 0, wx.EXPAND)
        panel.SetSizer(outer)

    def _build_portable_tab(self):
        s = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self.tab_portable, label=(
            "One operation snapshots the actual footprints already on the PCB, relinks the schematic to a project-local library, "
            "embeds resolvable 3D models inside each footprint using KiCad's native Embedded Files format, and can snapshot symbol libraries."
        ))
        intro.Wrap(950)
        s.Add(intro, 0, wx.ALL | wx.EXPAND, 14)

        box = wx.StaticBoxSizer(wx.VERTICAL, self.tab_portable, "What to make portable")
        self.cb_3d = wx.CheckBox(box.GetStaticBox(), label="Embed 3D models directly inside each footprint (recommended)")
        self.cb_3d.SetValue(True)
        self.cb_symbols = wx.CheckBox(box.GetStaticBox(), label="Create project-local symbol snapshot libraries and relink symbols")
        self.cb_symbols.SetValue(True)
        self.cb_vault = wx.CheckBox(box.GetStaticBox(), label="Mirror generated footprint/symbol source files into Schematic + Board Embedded Files vault")
        self.cb_vault.SetValue(True)
        self.cb_perref = wx.CheckBox(box.GetStaticBox(), label="Preserve per-reference PCB footprint edits (one exact snapshot per placed reference)")
        self.cb_perref.SetValue(True)
        self.cb_network = wx.CheckBox(box.GetStaticBox(), label="Allow direct HTTP/HTTPS 3D model downloads when a model path is a URL")
        self.cb_network.SetValue(False)
        self.cb_network.SetToolTip("Off by default. Enable only for reviewed model URLs; unresolved links remain unchanged.")
        for cb in [self.cb_3d, self.cb_symbols, self.cb_vault, self.cb_perref, self.cb_network]:
            box.Add(cb, 0, wx.ALL, 7)
        s.Add(box, 0, wx.ALL | wx.EXPAND, 10)

        safe = wx.StaticBoxSizer(wx.VERTICAL, self.tab_portable, "Safe transaction")
        safe_text = wx.StaticText(safe.GetStaticBox(), label=(
            "Apply creates timestamped backups and uses atomic file replacement. Because KiCad 9/10 does not expose all schematic/native-embedding edits through IPC, "
            "save and close open Schematic/PCB editors before Apply. You can launch this window from PCB Editor, then close the editor; this window stays open."
        ))
        safe_text.Wrap(930)
        safe.Add(safe_text, 0, wx.ALL | wx.EXPAND, 8)
        self.lock_label = wx.StaticText(safe.GetStaticBox(), label="Lock status: checking…")
        safe.Add(self.lock_label, 0, wx.ALL, 8)
        s.Add(safe, 0, wx.ALL | wx.EXPAND, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_analyze = wx.Button(self.tab_portable, label="Analyze Project")
        self.btn_apply = wx.Button(self.tab_portable, label="Make Project Portable")
        self.btn_apply.SetDefault()
        self.btn_analyze.Bind(wx.EVT_BUTTON, lambda e: self.run_analysis())
        self.btn_apply.Bind(wx.EVT_BUTTON, lambda e: self.run_apply())
        buttons.AddStretchSpacer(1)
        buttons.Add(self.btn_analyze, 0, wx.ALL, 6)
        buttons.Add(self.btn_apply, 0, wx.ALL, 6)
        s.AddStretchSpacer(1)
        s.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.tab_portable.SetSizer(s)

    def _build_assets_tab(self):
        s = wx.BoxSizer(wx.VERTICAL)
        self.asset_summary = wx.StaticText(self.tab_assets, label="Analyze the project to inventory assets.")
        s.Add(self.asset_summary, 0, wx.ALL | wx.EXPAND, 10)
        self.asset_list = dv.DataViewListCtrl(self.tab_assets, style=dv.DV_ROW_LINES | dv.DV_VERT_RULES)
        for title, width in [("Reference", 100), ("Type", 120), ("Source / link", 390), ("Status", 150), ("Destination / detail", 360)]:
            self.asset_list.AppendTextColumn(title, width=width, mode=dv.DATAVIEW_CELL_INERT)
        s.Add(self.asset_list, 1, wx.ALL | wx.EXPAND, 10)
        self.tab_assets.SetSizer(s)

    def _build_vault_tab(self):
        s = wx.BoxSizer(wx.VERTICAL)
        text = wx.StaticText(self.tab_vault, label=(
            "Vault mode keeps generated .kicad_mod and .kicad_sym source files in KiCad's native Embedded Files collection as a recovery copy. "
            "The active footprint link still points to the project-local PortableAssets library; 3D models are embedded at footprint scope."
        ))
        text.Wrap(950)
        s.Add(text, 0, wx.ALL | wx.EXPAND, 14)
        self.vault_status = wx.StaticText(self.tab_vault, label="Use Restore if a shared project has lost its .portable_assets folder.")
        s.Add(self.vault_status, 0, wx.ALL, 14)
        self.btn_restore = wx.Button(self.tab_vault, label="Restore .portable_assets from Embedded Vault")
        self.btn_restore.Bind(wx.EVT_BUTTON, lambda e: self.run_restore())
        s.Add(self.btn_restore, 0, wx.ALL, 14)
        s.AddStretchSpacer(1)
        self.tab_vault.SetSizer(s)

    def _build_repair_tab(self):
        s = wx.BoxSizer(wx.VERTICAL)
        text = wx.StaticText(self.tab_repair, label=(
            "Repairs broken schematic footprint-library links from the full footprint geometry that is already stored in the PCB. "
            "The recovered .kicad_mod keeps pads, courtyard, fabrication/silkscreen drawings, custom graphics, zones/groups and 3D references; board-only placement/net data is removed."
        ))
        text.Wrap(950)
        s.Add(text, 0, wx.ALL | wx.EXPAND, 14)
        self.repair_list = wx.CheckListBox(self.tab_repair)
        s.Add(self.repair_list, 1, wx.ALL | wx.EXPAND, 10)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_repair_scan = wx.Button(self.tab_repair, label="Find Missing Links")
        self.btn_repair = wx.Button(self.tab_repair, label="Repair Selected from PCB")
        self.btn_repair_scan.Bind(wx.EVT_BUTTON, lambda e: self.load_missing())
        self.btn_repair.Bind(wx.EVT_BUTTON, lambda e: self.run_repair())
        row.AddStretchSpacer(1)
        row.Add(self.btn_repair_scan, 0, wx.ALL, 6)
        row.Add(self.btn_repair, 0, wx.ALL, 6)
        s.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        self.tab_repair.SetSizer(s)

    def options(self):
        return PortableOptions(
            embed_3d=self.cb_3d.GetValue(),
            snapshot_symbols=self.cb_symbols.GetValue(),
            mirror_vault=self.cb_vault.GetValue(),
            per_reference_footprints=self.cb_perref.GetValue(),
            allow_network=self.cb_network.GetValue(),
        )

    def open_help(self, _event=None):
        help_path = Path(__file__).resolve().parents[1] / "help.html"
        if not help_path.exists():
            wx.MessageBox("The bundled help file is missing.", "WayriCAD Portable Assets", wx.OK | wx.ICON_ERROR, self)
            return
        webbrowser.open(help_path.as_uri())

    def _current_signature(self, options=None):
        options = options if options is not None else self.options()
        option_key = (
            options.embed_3d,
            options.snapshot_symbols,
            options.mirror_vault,
            options.per_reference_footprints,
            options.allow_network,
            tuple(options.model_search_roots),
        )
        return project_signature(self.ctx), option_key

    def _post(self, callback, *args):
        # Workers only enqueue Python callbacks; native control lifetime is checked on the UI thread.
        def deliver():
            if self and not self.IsBeingDeleted():
                callback(*args)
        wx.CallAfter(deliver)

    def append_log(self, line: str):
        if not self or self.IsBeingDeleted():
            return
        self.log.AppendText(line.rstrip() + "\n")

    def set_progress(self, message: str, pct: int):
        self._post(lambda: self.status.SetLabel(message))
        self._post(lambda: self.progress.SetValue(max(0, min(100, pct))))

    def _set_busy(self, busy: bool):
        if not self or self.IsBeingDeleted():
            return
        self._busy = busy
        for b in [self.btn_analyze, self.btn_apply, self.btn_restore, self.btn_repair_scan, self.btn_repair]:
            b.Enable(not busy)

    def _thread(self, name, fn, done=None):
        if self._busy:
            return
        self._set_busy(True)
        self.append_log(name)
        def worker():
            try:
                result = fn()
                self._post(self.append_log, f"✓ {name} complete")
                if done:
                    self._post(done, result)
            except Exception as exc:
                detail = traceback.format_exc()
                self._post(self.append_log, f"✗ {exc}\n{detail}")
                self._post(wx.MessageBox, str(exc), "Portable Assets", wx.OK | wx.ICON_ERROR, self)
            finally:
                self._post(self._set_busy, False)
        threading.Thread(target=worker, daemon=True).start()

    def run_analysis(self):
        if not self or self.IsBeingDeleted():
            return
        options = self.options()
        self.progress.SetValue(0)
        self._analysis_signature = None

        def analyze():
            before = self._current_signature(options)
            report = scan_project(self.ctx, options)
            after = self._current_signature(options)
            if before != after:
                raise RuntimeError("Project files or options changed during analysis. Analyze again before applying.")
            return report, after

        self._thread("Analyzing project", analyze, self._analysis_done)

    def _analysis_done(self, result):
        report, signature = result
        self._report = report
        self._analysis_signature = signature
        self.progress.SetValue(100)
        self.status.SetLabel("Analysis complete")
        self.lock_label.SetLabel("Lock status: " + ("OPEN EDITOR / LOCK DETECTED — close editors before Apply" if report.locks else "clear"))
        self.asset_summary.SetLabel(
            f"{report.footprints} PCB footprints • {report.schematic_symbols} schematic symbols • "
            f"{report.model_refs} 3D references • {report.unresolved_models} unresolved models • "
            f"{report.missing_footprint_links} missing footprint links"
        )
        self.asset_list.DeleteAllItems()
        for a in report.assets:
            detail = a.destination or a.detail
            self.asset_list.AppendItem([a.reference, a.kind, a.source, a.status, detail])
        for w in report.warnings:
            self.append_log("Warning: " + w)
        self.load_missing()

    def run_apply(self):
        locks = self.ctx.lock_files()
        if locks:
            msg = (
                "KiCad lock files are present. Save and close the Schematic and PCB editors first.\n\n"
                "This plugin writes native embedded-file data directly to the project files because KiCad 9/10 does not expose those edits through IPC. "
                "Keeping an editor open could overwrite the result on its next save.\n\n"
                "After closing the editors, leave this Portable Assets window open and click Make Project Portable again."
            )
            wx.MessageBox(msg, "Close KiCad editors before Apply", wx.OK | wx.ICON_WARNING, self)
            return
        if self._report is None or self._analysis_signature is None:
            wx.MessageBox("Analyze the project and review the Assets table before applying.", "Preview required", wx.OK | wx.ICON_INFORMATION, self)
            return
        if self._current_signature() != self._analysis_signature:
            self._analysis_signature = None
            wx.MessageBox("Project files or portability options changed after analysis. Analyze again before applying.", "Stale preview", wx.OK | wx.ICON_WARNING, self)
            return
        confirmation = (
            f"Apply the reviewed portability plan?\n\n"
            f"PCB footprints: {self._report.footprints}\n"
            f"Schematic symbols: {self._report.schematic_symbols}\n"
            f"3D references: {self._report.model_refs}\n"
            f"Unresolved models left unchanged: {self._report.unresolved_models}\n"
            f"Network downloads: {'enabled' if self.options().allow_network else 'disabled'}\n\n"
            "Timestamped backups are created before any file is replaced."
        )
        if wx.MessageBox(confirmation, "Confirm reviewed transaction", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        def done(result):
            self.progress.SetValue(100)
            self.status.SetLabel("Project is portable")
            self.append_log(f"Backup: {result.backup_dir}")
            self.append_log(f"Localized {result.footprints_localized} footprints, {result.symbols_localized} symbols; embedded {result.models_embedded} model references.")
            if result.unresolved_models:
                self.append_log("Unresolved model paths left unchanged:\n  " + "\n  ".join(result.unresolved_models))
            wx.MessageBox(
                f"Portable project created.\n\nFootprints: {result.footprints_localized}\nSymbols: {result.symbols_localized}\n3D model refs embedded: {result.models_embedded}\n\nBackup: {result.backup_dir}",
                "Portable Assets", wx.OK | wx.ICON_INFORMATION, self)
            self._analysis_signature = None
            self.run_analysis()
        options = self.options()
        self._thread("Making project portable", lambda: make_portable(self.ctx, options, self.set_progress), done)

    def load_missing(self):
        try:
            items = missing_footprints(self.ctx)
        except Exception as exc:
            self.append_log(f"Could not scan missing footprints: {exc}")
            return
        self.repair_list.Clear()
        self._repair_items = items
        for i, a in enumerate(items):
            self.repair_list.Append(f"{a.reference}   {a.source}   → recover exact footprint from PCB ({a.detail})")
            self.repair_list.Check(i, True)
        if not items:
            self.repair_list.Append("No missing project/local footprint links detected.")

    def run_repair(self):
        items = getattr(self, "_repair_items", [])
        refs = [a.reference for i, a in enumerate(items) if self.repair_list.IsChecked(i)]
        if not refs:
            wx.MessageBox("Select at least one missing footprint to repair.", "Portable Assets", wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.ctx.lock_files():
            wx.MessageBox("Save and close KiCad editors before repairing project files, then retry.", "Portable Assets", wx.OK | wx.ICON_WARNING, self)
            return
        if wx.MessageBox(
            f"Repair {len(refs)} reviewed footprint link(s) from PCB snapshots?\n\nA timestamped backup is created first.",
            "Confirm footprint repair", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
        ) != wx.YES:
            return
        opts = self.options()
        opts.snapshot_symbols = False
        opts.mirror_vault = False
        def done(result):
            self.append_log(f"Repaired {result.footprints_localized} footprint link(s). Backup: {result.backup_dir}")
            self.load_missing()
            wx.MessageBox(f"Repaired {result.footprints_localized} footprint link(s).", "Portable Assets", wx.OK | wx.ICON_INFORMATION, self)
        self._thread("Repairing missing footprints", lambda: repair_missing_footprints(self.ctx, refs, opts, self.set_progress), done)

    def run_restore(self):
        if self.ctx.lock_files():
            wx.MessageBox("Save and close KiCad editors before restoring project-local libraries, then retry.", "Portable Assets", wx.OK | wx.ICON_WARNING, self)
            return
        if wx.MessageBox(
            "Restore project-local library files from the reviewed Embedded Files vault?\n\nExisting targets are backed up first.",
            "Confirm vault restore", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
        ) != wx.YES:
            return
        def done(paths):
            self.append_log(f"Restored {len(paths)} file(s) from the Embedded Files vault.")
            wx.MessageBox(f"Restored {len(paths)} portable library file(s).", "Portable Assets", wx.OK | wx.ICON_INFORMATION, self)
        self._thread("Restoring Embedded Files vault", lambda: restore_from_vault(self.ctx), done)
