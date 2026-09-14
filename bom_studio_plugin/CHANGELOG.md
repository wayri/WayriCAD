# 0.8.3 — complete assembler-export integration

- Dedicated OEM / assembly export GUI; JLCPCB, PCBWay, HQPCB, NextPCB, Sierra Circuits, PCB Power, Seeed and Generic mappings.
- Per-board quantities independent from distributor routing, build counts, attrition and MOQ.
- Single CSV/XLSX/TSV and multi-profile ZIP with excluded-parts audit and integrity manifest.
- Property mappings, configurable output columns, protected required columns, explicit review status and stale-preview guards.
- CLI assemblers and optional assembler_exports pipeline gate; all previous functions retained.
- Full PCM package; no manual profile-pack merge. Actual KiCad/Windows/macOS host and production portal acceptance remain unexecuted.

# 0.7.1 — PCM packaging and native KiCad BOM icons

* New direct Install-from-File archive: root metadata.json and flat plugins payload.
* PCM runtime=ipc; current PCM/API schemas checked; no legacy SWIG registration.
* Standard KiCad file_bom artwork: light/dark 24/48/96 toolbar arrays, 64-pixel PCM image, additional raster sizes and unchanged SVG sources.
* Required artwork attribution and separate code/artwork licenses.
* Standalone launchers corrected for the PCM directory layout; full v0.7 engine retained.
* Reproducible ZIP builder, validation helper, packaging regressions and current install guide.
* No assertion of KiCad-host, Windows/macOS or future-version certification.

# 0.7.0 — Searchable catalogue with retained symbol/footprint/3D assets

* Independent catalogue browsing, metadata and typed AND filters; coherent asset-completeness filters before pagination.
* Content-addressed capture of model originals, embedded Zstandard/checksum validation, native/custom library and variable paths, all hidden/alternative model references and preserved transforms.
* Source-set/revision inspector, bounded generated symbol/footprint SVG, interactive original-model preview and byte-identical model downloads. Optional OpenCascade converter is separate from storage.
* Native symbol/footprint/model library ZIP with relinked hashes, source-set ambiguity checks and explicit completeness policy. Original projects and library tables are never rewritten by export.
* CLI assets/preview/asset-export; extended search/harvest/native-export; doctor capability reporting. Asset-only output and large-plan handling remain narrowly bounded.
* Kept old catalogue revisions, all earlier BOM/engineering workflows, original source permissions and known host-validation boundaries. Re-harvest old records to acquire models.

# 0.6.0 — Engineering catalog and controlled reuse

* Separate versioned SQLite/FTS catalog with internal numbers, project harvesting/provenance, native assets/export, conflict retention and full catalog health scanning.
* Explainable row-level recommendations with rating/risk guards and reviewed application.
* Declared land-pattern geometry/pin-function comparison and local context-bound qualification/alternate/release decisions, expiring scoped waivers and optional controlled pipeline gate.
* BOM-only derived/pinned variants, rename/reparent/tags/locks, safe native-sync exclusion.
* Multi-build inventory/supplier-pool simulation, typed lead times, MOQ/multiples/tiers, explicit split review and correct surplus reuse accounting.
* Source-linked missing-mass proposals with explicit estimate basis and analytics warnings.
* Bounded ungrouped BOM DOM window, indexed catalog paging, read-task progress/cancel, keyboard and text+color accessibility improvements.
* Ten new CLI families (33 total), engineering sample and real-host acceptance recorder. Host-unavailable results are never promoted to native pass.
* Fixed inherited repeated health-settings keyword merge failure.

Developer preview. Actual native KiCad/SDK transport, Windows/macOS hosts, KiCad 11, real distributor extraction and assistive screen-reader acceptance remain unexecuted. See current TEST_REPORT.md.

## Historical releases

# 0.4.0 — 9 September 2026

- Shared bounded GUI/CLI search DSL, facet chips, saved filters and data-only sharing.
- Explicit full-result/selected/hidden bulk scopes, group/member checkboxes, ordered field recipes and reviewed FIT/DNP/DNI shortcuts.
- 21 command families with versioned JSON/exit codes, stdin, no-overwrite outputs, review/apply separation and legacy syntax compatibility.
- Multi-variant policy-gated pipelines, workspace snapshots, reports and SHA-256 integrity verification; no BOM exports on failed gates.
- Native KiCad job-set/runner bundle generation, JOBSET_OUTPUT_WORK_PATH integration and explicit detached interactive GUI launch.
- Optional selection-only official IPC adapter with saved-project discovery, UUID instance mapping, bidirectional PCB selection, pad/field ownership, echo suppression, filter reveal and edit-focus protection. Native schematic relay and optional zoom remain untested in KiCad.
- More complete inherited-variant edit review and physical-field alias sequencing. Deleted starter templates no longer reappear during version migration.
- 419 backend tests and 81 browser checks in the documented bridged/fake-IPC environment. KiCad/official SDK host, native job sets, Windows/macOS and KiCad 11 untested. Complete CLI, workflow, compatibility and future roadmap documentation.

# 0.3.0 — 2026-09-09

- Direct in-grid Value/Footprint/MPN/custom field editing with queued drafts, CSV/TSV paste, reviewed multi-cell atomic workspace edits and native-write separation.
- Any-field/raw-expression presentation grouping, mixed-value display and expandable/member-wide reviewed edits; existing export compatibility guards retained.
- Offline explainable passive-value normalization, exact-identity demand and consolidation assessments with constraints/unknowns.
- Read-only local library/PCB pad geometry, embedded symbol pins, exact-MPN evidence comparisons and stock freshness/market/MOQ screening.
- No-key DigiKey/Mouser website round-trip CSV, mapped CSV/TSV/XLSX/JSON evidence imports, reviewed ledger and optional activeTab-only product-page capture extension.
- Explicit unknowns, exact orderable suffix matching, stale-report indicators, separate health/analysis JSON export, input validation and regression tests.
- Still a developer preview: no actual KiCad/Windows/macOS/live-distributor/extension-host qualification. See current test report.

# Changelog

## 0.2.0 — 2026-09-09 — Developer preview

Implemented independently ordered/visible workspace columns, table-header drag, named shared layouts, explicit export inclusion, custom BOM template CRUD/sharing/import and template metadata. Added UTF-8/ASCII reports, ODS, generic XML, JSONL and Markdown; configurable delimited-text encoding, quoting, newline and raw/resolved modes. Added generic ERP and JLCPCB/LCSC starter mappings.

Implemented reviewed field-name templates and project-wide enforcement across all supported variants: Merge/Exact schema, default Preserve/Fill/Reset, ordinary case and explicit alias migration, separate name/value baking, expression-loss preview, destructive confirmation, one-step session undo and native project field-default registration. Native synchronization remains separate and backed up. Generated `${NAME}` properties use KiCad's linked-value semantics; independent values are rejected. Raw alias exports retain source expressions. Nested/escaped/math expressions are now explicitly blocked rather than partially evaluated.

Added backend and browser coverage for all new workflows, generated-field guards and native round trips through the package adapter. No actual KiCad-host, Windows or macOS validation is claimed. See TEST_REPORT.md for executed counts and limitations.


## 0.1.0 — 2026-09-09 — Developer preview

Initial working offline BOM workspace, KiCad IPC launcher bundle, native-variant parser and reviewed writeback, hierarchy/repeated-instance handling, population matrix, field and project variables, procurement assumptions, alternate decisions, export templates and release integrity manifests. Includes synthetic sample fixtures, backend/security tests, optional browser acceptance tests and recovery documentation.

Not certified for production, Xpedition equivalence, KiCad 11, or an untested host/format combination. See the compatibility and test reports before use.
