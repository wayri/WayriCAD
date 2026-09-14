# WayriCAD 0.8.1 — Native-first formats and reliable launch

Released 10 September 2026. Full PCM package. This document supersedes prior statements that initial export selects Purchasing, native omitted fields are appended, or field templates initially select Engineering standard.

## Authority and migration

`bom_preferences` stores mode (`native`/`custom`), the selected saved/named native BOM and formatting presets, and the explicit custom-template choice. Workspaces without this preference migrate to native mode. Existing custom templates, field profiles, layouts and component edits remain stored. A migrated custom layout is not assumed to represent an intentional request to override native settings.

In native mode the read API constructs the visible view without modifying saved custom view state. An explicit column/grouping customization detaches the view into custom mode. Following native again reconstructs the view from saved native settings. There is no automatic global/native write.

## Native fields and formats

Project `.kicad_pro` field definitions are JSON entries. Global `eeschema.json` uses KiCad's templatefields S-expression representation; both are read. Exact matching project names override globals. Mandatory property names are not treated as additional template fields. Case is preserved, including variable tokens. Project/global source and schematic visibility/URL metadata appear in the read-only field-template view. Default property values and required-field rules are not invented.

The saved native `bom_settings.fields_ordered` controls displayed membership, labels and order. Columns deliberately omitted or hidden are available in Project fields, not automatically promoted. Definitions with no component property are shown as empty placeholders without materializing fields. Saved format presets preserve delimiter, string quoting, reference separators/range separators and keep-tabs/line-break flags. UI columns are capped at 200 with disclosure; configured native output retains all columns within input validation limits.

Without a saved BOM setting, the native Default Editing column model is used, followed by declared/discovered fields. This is a fallback view, not a claim that the complete native table implementation runs inside WayriCAD. Supported variable-column display retains unresolved expressions and warnings rather than blanking them. Physical values/raw expressions are separate from derived aliases.

The native workspace grid's grouping/filtering is an inspection implementation. Arbitrary native expression contexts and effective rule-area attributes are not independently qualified. Native saved-output fidelity comes from the installed KiCad engine, not a claim of identical custom grouping.

## Native export

Native preview/export requires an explicit saved-data acknowledgement and the installed KiCad command. `kicad-cli version` and `sch export bom --help` determine supported options. Current saved fields/labels/group keys, sort/filter and all formatting settings are passed explicitly: relying on the CLI's own default fields would be incorrect. A selected named preset is sent by name. Field/label lists containing embedded commas cannot be faithfully encoded through a current CLI list option; select a named native preset instead of accepting a changed name.

Output bytes are returned unmodified, including native delimiters, newlines and expressions. Native text is not sanitized by WayriCAD's spreadsheet formula protection: treat untrusted native CSV appropriately. Files are hash-checked before and after export. Unknown flags, missing executable, native failures and unsupported filter scope produce an error, not a guessed custom-export fallback.

Saved native files do not contain unreviewed grid edits, unsaved workspace/editor changes or BOM-only variants. No hidden synchronization is performed. The rule-area inspection block remains on WayriCAD's independent engine and native write adapter; exporting with KiCad does not suppress it.

## Explicit customization and merging

Customize a copy creates a named WayriCAD template and activates custom mode after review of conversion differences. Imported native hidden column definitions are retained as unchecked entries. Unsupported custom quoting/delimiter, reference-filter, descending-sort and multiline behavior is disclosed. An existing name is not silently overwritten.

Merge missing KiCad columns adds missing source fields to a selected existing custom template. Existing custom order, labels and options take precedence. No source properties, global preferences or native settings are changed by copy/merge. The existing enhanced exports, variants, quantities and purchasing safeguards remain available in custom mode.

The read-only native field-template screen has a separate Copy action that copies names/visibility/URL metadata only. Manage custom profiles opens the established explicit Enforce workflow. Neither choosing an export template nor saving a read-only native screen enforces a component schema.

## Reverse custom format → KiCad

The reverse preview contains both complete settings objects and a unified diff. It binds project/workspace/template data and the current global-template source hash. Positive inclusion aliases are not silently inverted; use an explicit native exclusion expression. Custom price/calculated/ambiguous alias columns without a native physical source are refused. WayriCAD-only scoped expressions in names/labels and DNP-only population are refused when not representable. Native reference filters are reset and native sort is ascending for this custom-export mapping; the preview discloses that.

Typing FORMAT with replacement acknowledgement stages `native_bom_settings` as one undoable workspace operation. It does not write any `.kicad_pro`, `.kicad_sch`, global preferences or component properties. Save workspace persists the staged choice. The separate reviewed backed-up native APPLY writes supported changes with editors closed. Adapter reload checks the new BOM settings and verifies staged data. This is not a real KiCad reload or power-loss-atomic transaction. Existing field enforcement/variable and source-drift safeguards remain.

## Desktop-only toolbar action

The unchanged package/action identity now points to `desktop_entrypoint.py`. That entrypoint appends desktop mode and refuses UI override/headless arguments. Standalone CLI may request browser mode deliberately. No exception path silently calls an external browser for the main UI.

The visible runtime badge identifies version and desktop/browser/headless mode. Runtime diagnostics show actual installation, entrypoint, interpreter and PID, and perform a bounded read-only duplicate-manifest scan. Old processes must be quit and old manual installations moved outside scanned directories. The scanner does not guarantee finding every custom installation and never deletes user data.

The UI is a separate modeless IPC-plugin window containing a webview, not a native wxWidgets/docked panel. Embedded engines need platform dependencies. Actual engine hosting and native cross-selection are target-system checks, not inferred from browser tests.

## Regression fixes

The common dialog submit handler closes only the form that was submitted. A newly opened review/difference dialog is no longer immediately closed by the previous callback. Submission errors remain in the current review dialog.

Exact physical-property inline editing checks the raw original name rather than `@field:`-prefixed display keys. Mandatory Reference remains read-only; custom physical Qty/Source values stay distinct from computed columns. Bounded virtual tables preserve total-row accessibility metadata even when table CSS adds classes. All current UI scripts are included in the release browser tests; older custom-workflow regressions explicitly select their custom setup rather than bypassing native-first code.

## CLI additions and changed defaults

37 command families. `bom-format` subcommands: show, follow, customize, merge, use-custom, preview, apply. Read-only show/preview can use --source-only; mutating preference/copy/apply commands reject it to prevent overwriting saved component changes from an ignored sidecar.

`native-bom` without a configuration inherits selected native settings. `export` without --template uses native CSV and needs --acknowledge-saved-only. Other enhanced export formats need an explicit --template. Multi-variant `release` requires --template. Existing pipeline JSON explicitly selects its template; no automatic template enforcement is inserted into job sets. Existing legacy positional syntax is retained for compatibility and remains a custom-engine route with a migration warning.

## Acceptance scope

Read TEST_REPORT.md for actual final counts. Native CLI process calls are injected in contract/GUI tests because no KiCad installation is present. Browser checks use the real shipped HTML/CSS/JavaScript and authenticated backend through the documented HTTP bridge. Real native export, PCM GUI install, Windows/macOS embedded engines, real IPC relay/focus, job-set host, complete screen-reader acceptance and KiCad 11 remain unexecuted.
