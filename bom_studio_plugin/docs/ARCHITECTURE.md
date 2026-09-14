> **v0.7 update:** symbol/footprint/model capture, independent catalogue browsing and preview, source-set selection and complete-reference native ZIP export are implemented. See V7_WORKFLOWS.md for current asset behavior; prior “3D omitted” limitations are historical. Real KiCad-host validation is still outstanding.

# Version 0.4 boundaries

> **0.6 update:** V6_WORKFLOWS.md, CONTROL_TRUST.md, HOST_ACCEPTANCE.md and the current TEST_REPORT.md describe the new persistent catalog, independent variants, review gates and remaining validation boundaries. The material below retains earlier subsystem details; the current update takes precedence where extended.

search.py is the shared bounded query engine. actions.py compiles ordered data-only recipes into existing reviewed bulk edits. configedit.py stages allowlisted configuration transactions. automation.py provides read-only policy-gated pipelines, manifest verification and native job-set generation. cli.py supplies stable command families and JSON/exit semantics. launch.py supports explicit detached GUI startup. bridge.py owns optional IPC on one worker thread and only reads editor items/changes selection, with a single opt-in zoom action. web/automation.js integrates query/bulk/live/automation views after the three previous scripts. Saved data, live selection, edit target selection and pending grid drafts remain separate states.

---

# Architecture and extension contract

The runtime is Python 3.10+ standard library plus static HTML/CSS/JavaScript. No package download is needed for normal operation. Tkinter is optional for the file picker. Development tests optionally use Playwright and a separately installed Chromium.

`sexpr.py` is a bounded scanner/AST with exact source spans. Edits are ranges, not a full schematic pretty-printer. Parentheses and escaped quotes inside strings remain data. Overlapping modifications are rejected. Unknown subtrees outside edited supported fields are preserved as original source text.

`native.py` loads project JSON and schematic hierarchy, collects instance paths, merges consistent same-sheet units, recognizes native variants and inherited sheet attributes, and records source hashes. Historical variant in_bom semantics are version-gated. Any new format coverage belongs here with fixtures and host comparisons, not in UI conditional guesses.

`engine.py` owns the sidecar schema, base/variant overlays, inheritance, resolver, aliases, validators, alternate decisions, import previews, history and undo/redo. It exposes effective raw and resolved fields separately. Stored native booleans remain distinct from assembly intent labels and output filtering. UUID/path identity links edits to components, not row positions.

`exporters.py` groups only compatible rows, calculates Decimal quantities/costs, emits CSV/TSV/JSON/HTML/minimal OOXML XLSX and dispatches additional formats to `textformats.py` and bundles all variants with integrity manifests. It is deliberately a snapshot exporter. Imported text is never executed as a spreadsheet formula. SHA-256 is integrity checking, not signing.

`catalog.py` validates/migrates portable data-only export templates, native-field profiles and ordered view presets. It supports explicit import collision policies and does not export project rows/variables implicitly. `textformats.py` implements wrapped UTF-8/ASCII reports, generic XML, JSONL, Markdown and basic ODS packaging.

`enforcement.py` transforms the effective raw fields across default + all variants into an exact staged schema. It preserves source-property metadata through rename mappings, protects mandatory/simulation fields and population flags, requires previews and typed confirmation, detects name/alias/shared-instance conflicts and can register native project field-name defaults. `field_schema_edits` snapshots explicit field order and tracks inherited/reset-to-base keys so future parent edits remain meaningful. Generated KiCad fields are recognized by their exact native name rule and their value is never treated as independently editable.

`writeback.py` compiles native diffs separately from applying them. It rejects unsupported formats/variables, requires a reviewed fingerprint, backups and explicit confirmation, and verifies a native adapter round trip. Original files and sidecar are included in the recoverable transaction. Power-loss atomicity is not promised.

`server.py` owns the loopback-only HTTP server, token/Host/Origin protections, request-size bounds, static allowlist, and a process-local workspace mutation lock. It dispatches to engine functions without shell commands. The optional picker runs a fixed entrypoint in a subprocess; user strings are never interpolated into a shell command. `compat.py` probes fixed CLI argument arrays with timeouts.

`web/workbench.js` extends the base UI with column/layout managers, template sharing, export options and field-enforcement review. Both scripts are loaded in order before the initial refresh. `web/app.js` is an offline DOM UI with escaped user text, explicit dialogs, field provenance, variant matrix, forms and export controls. It is not an editor-memory API. `entrypoint.py` supports both the IPC launcher and direct use. `python -m bomstudio` is the shared-engine automation interface.

## Recommended next engineering stages

First, capture representative real KiCad 10 fixture projects, including multiple units, repeated hierarchies, BOM-excluded mechanics, embedded model-heavy parts, variant field changes and realistic project settings. Compare ungrouped references, quantities, effective fields and flags against native CLI exports for every variant. Run host read/write/save/reopen and PCB-update tests on Windows, Linux and macOS. Report every skipped format case explicitly.

Then implement scoped live IPC integration only for documented available capabilities, native preset conversion with round-trip tests, independent variant duplication/rename/delete with full record coverage, organization-owned template libraries, richer three-way conflict review, and role-controlled supplier/PLM connectors as separate optional packages.

KiCad 11 support should be introduced by a new tested capability/format adapter with explicit migration policy, not by relaxing `SAFE_VERSION`. Rule-area or future pin-map/symbol-override features require actual native semantics and geometry/pin validation. Do not remove fail-closed gates to make a project appear supported.

The sidecar is intentionally a local editable JSON format. It is not a secured database, transaction server, access-control system or immutable engineering approval ledger. Those enterprise properties require a different persistence and identity layer.


## Additive workspace compatibility

v0.2 retains schema number 1 and adds `view`, `view_presets`, `field_profiles`, `field_schema_edits`, `native_field_templates` and catalog metadata. Definitions are explicitly validated; component identities remain UUID/path-based. Loading v0.1 adds missing defaults and preserves existing same-name templates. There is no safe automatic downgrade to v0.1, whose engine cannot interpret staged schema removals. The original workspace must be backed up before upgrade.


## 0.3 intelligence layer

`bulkedit.py` normalizes real field aliases, simulates edits on a shadow workspace and fingerprints reviewed effects before a single commit. `evidence.py` parses bounded tables/XLSX/capture JSON and validates a separate canonical ledger. `footprints.py` reads local symbol/pad facts with source hashes. `intelligence.py` provides deterministic normalization, demand/stock assessments and advisory health findings. `web/intelligence.js` adds direct editing, grouped presentation, reports and reviewed import workflows. The optional extension lives outside the KiCad plugin directory and never communicates directly with the local server; JSON is deliberately reviewed/imported by the user. No distributor HTTP client exists in the runtime.

These reports do not mutate the design or change the existing production-export gate. Imported evidence is not independently authenticated. Native writeback remains in `writeback.py`; board and footprint-library facts are read-only. Grouping is view state, not purchasing equivalence.


## 0.5 quantitative layer

`measures.py` provides bounded Decimal parsing, explicit dimensions and affine C/F/K conversion. `analytics.py` validates mapping/configuration, resolves entered data, separates purchasing/physical scopes, pools guarded order lots and computes cost/mass/power/statistics/budgets. `analytics_exports.py` serializes advisory snapshots without using optional spreadsheet runtime packages. `search.py` shares the typed numeric parser; `engine.public` uses saved price mappings for the full-variant KPI. GUI `analytics.js`, CLI analytics/threshold commands and pipeline stages call the same Python implementation. All field/native-edit transactions remain separate.

Configuration lives in the schema-1 sidecar under `analytics_settings`; older sidecars receive defaults. It is never serialized as a KiCad native property or silently pushed into an existing export template. The dedicated synthetic analytics example is copied to a temporary directory by `--analytics-demo`. The primary server still binds only to authenticated loopback; no supplier/model/network service is added.
