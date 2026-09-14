# Version 0.4 automation and live selection

> **0.6 update:** V6_WORKFLOWS.md, CONTROL_TRUST.md, HOST_ACCEPTANCE.md and the current TEST_REPORT.md describe the new persistent catalog, independent variants, review gates and remaining validation boundaries. The material below retains earlier subsystem details; the current update takes precedence where extended.

Review complete target scope before EDIT, including hidden checked rows and inheriting variants. CLI mutation commands save the sidecar; reload any open GUI afterward. Native APPLY remains separate and requires closed KiCad editors. Pipelines do not mutate native/workspace files but include the complete workspace snapshot and absolute source paths in their new output directory; treat them as sensitive. Integrity verification is not signing or approval, and FAILED pipelines can have valid hashes. GUI --detach receipts contain a private session URL; do not log/share that receipt. Live editor highlights are separate from bulk edit selection. The IPC adapter does not edit/save board objects, but changes selection; opt-in RunAction zoom remains unstable and may have host side effects.

---

# Safety, conflicts, and recovery

## Before first use

Make a separate project copy or a known-good Git commit. Save the project in KiCad. Open that saved root in WayriCAD, verify component counts, inspect all supported variants, and compare at least one ungrouped BOM against KiCad's own native export. Keep the native export and field/flag inspection as the host source of truth until the adapter is validated on your design style.

## Workspace versus native files

Workspace edits reside in memory until Save workspace writes the sidecar. Session undo/redo works before native sync; the activity history is retained in the sidecar, but undo stacks are not persisted. Existing sidecars are backed up before replacement. An external sidecar modification blocks saving so another session is not silently overwritten.

Native sync is a separate reviewed operation. The preview is bound to the current workspace serialization, revision and source-file hashes. Any intervening edit or saved source modification invalidates the operation. The app checks for KiCad lock files, but cannot reliably observe unsaved editor memory or every file-lock convention. Close every editor yourself before applying.

The native compiler surgically changes recognized symbol properties/flags and instance variant records. Unrelated schematic text is retained. Project JSON is reserialized with its existing unknown keys preserved. No PCB or geometry writer exists in this package.

## Native transaction sequence

1. Confirm format, hierarchy, source hashes, variable-scope constraints, and an explicit reviewed fingerprint.
2. Confirm all KiCad editors are closed; require the literal text `APPLY`.
3. Build candidate source files and checkpointed workspace state.
4. Save original bytes and SHA-256 values in a new timestamped backup directory.
5. Flush candidate files to same-directory temporary files; recheck expected originals immediately before replacement.
6. Replace each file and reload the resulting project through the adapter. Compare raw field and attribute semantics for all supported variants.
7. On an ordinary exception, restore each replaced original unless another process has modified the replacement. Keep the backups and a failure record.

A process termination, machine crash or power loss between replacements can leave a partially applied project. Multi-file replacement is not a database transaction. The backup directory and manifest are the recovery mechanism. `COMPLETED.txt` means the adapter's normal path completed; it is not KiCad/ERC/manufacturing certification.

## Recover from a failed/interrupted sync

Close KiCad and the BOM workspace. Find the timestamped directory under the project root's `.wayricad-bom-backups/`. Read `manifest.json`: each record gives the original absolute filename, the backup filename, and before/after SHA-256 values. `FAILED.txt`, when present, explains ordinary errors and any unsuccessful automatic restoration.

Compare the current file to the recorded hashes before restoring. Restore each affected original from its corresponding `.bak` file, including the workspace sidecar. A `backup: null` record denotes a file that did not exist before the transaction; remove a newly created file only after confirming it is still the transaction's after-hash and contains no subsequent work. Do not overwrite unrelated changes blindly.

Open the restored project in KiCad, inspect it, and run native checks. Review the transaction changes in Git where available. Backups are not automatically pruned.

## Source changes and project moves

While a workspace is open, saved source changes block export and native sync. Save the sidecar if needed, then Reopen source files. On reopening, old sidecar source hashes may no longer match. Review source changes externally, inspect pending overlays and field/variant diffs, and then explicitly type `REBASE` to acknowledge the new baseline.

REBASE is a human acknowledgement, not a three-way merge or automatic conflict resolution. Component UUIDs that no longer exist remain release-blocking orphaned overrides. Absolute-path hashes also change when projects move between machines/directories; review and acknowledge rather than silently trusting old context.

## Data privacy and local security

The UI server binds only to `127.0.0.1`, uses an ephemeral port by default, requires a random per-session API token, checks Host and Origin, uses no CORS allowance, and serves a small static-file allowlist. No CDN, telemetry, network sourcing, account or credentials are built in.

Do not expose the server through a reverse proxy or share its session URL. A local token does not protect against malicious software with access to your account. Plugin updates and workspaces remain local code/data that should be reviewed and versioned normally.

The adapter reads stored property text, including properties carrying KiCad's `private` marker. That marker is not treated as a confidentiality/access-control boundary. Audit exports, source/provenance columns, workspace snapshots, alternates and release manifests can contain proprietary text and absolute local paths. Select appropriate export columns and inspect ZIP contents before sharing. No data is uploaded automatically.


## 0.2 field-template enforcement

Enforce is not a visibility control. Exact schema, Reset defaults, alias/case migration and name/value baking can remove useful custom properties or variable expressions from **every supported variant**. Review additions/removals/overwrites and native project defaults, retain a Git/project backup and inspect the downloadable full review. The warning and typed ENFORCE confirmation do not make a destructive plan reversible after arbitrary later work. Undo is session-local; native backups preserve original bytes.

Project-variable definitions themselves are not deleted. However, removing a field that contains `${REV}` loses that field's expression even when REV remains defined; these are separate effects. Conflicting alias values are blocking errors, not a heuristic merge. Generated `${NAME}` fields cannot retain an unrelated custom value in KiCad; contradictions are blocked explicitly.

Sharing a data-only template bundle omits project rows, variable definitions and file hashes, but a literal default/label/author/description can contain confidential material. Import never auto-enforces. Release ZIPs and full enforcement review JSON are different: they may contain raw project/component data and must be reviewed before sharing.

Before upgrading, back up both native files and the `.wayricad-bom.json` sidecar. Never mix v0.1/v0.2 static assets or run both versions against one project. v0.1 does not understand v0.2 staged schemas, so do not downgrade an updated workspace into the older app.


## 0.3 drafts, evidence and health

Unstaged in-browser grid drafts are not saved/exported. Review with EDIT first, then Save workspace; native APPLY remains separate. Evidence import is a different review requiring IMPORT. Never infer a qualified footprint from equal pin count, a part match from a shortened MPN, or available stock from a bare InStock label. Snapshot stock is not reserved or authenticated. Health is advisory, not an enforced manufacturing gate. Reports and release sidecars can include private part data, observed prices, local paths and source URLs; inspect before sharing. User-supplied evidence hashes are consistency checks, not digital signatures.
