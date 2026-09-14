# Real KiCad-host acceptance — 0.6.0

## Actual status in this development environment

**UNAVAILABLE: no usable KiCad or kicad-cli installation.** An official KiCad 10 Linux Lite AppImage download was attempted but the download failed; no KiCad binary is bundled. The actual hosttest invocation recorded CLI discovery SKIPPED and returned exit 6. Automated adapter/fake-driver tests are not substituted for native results.

| Acceptance | Linux native KiCad | Windows | macOS | KiCad 11 |
|---|---|---|---|---|
| Plugin discovery and launch | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| Native reload after field/variant edits | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| Job-set Execute Command/output collection | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| PCB ↔ BOM and schematic relay/focus | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| Generated `.kicad_sym/.pretty` loading | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |
| Screen-reader acceptance | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED | NOT EXECUTED |

Only the standalone Linux application/server/CLI, Linux file installation, synthetic browser workflows and parser/adapter tests have executed here. Full current details are in TEST_REPORT.md.

## Run on each target machine

From the plugin directory:

```sh
python cli.py doctor
python cli.py hosttest --project /absolute/disposable/Board.kicad_pro --directory /absolute/new-host-report
# Specify --kicad-cli /absolute/path/kicad-cli when it is not on PATH.
```

The recorder copies a bounded self-contained project into the new output directory (up to 2,000 files / 100 MiB). It rejects external child sheets that cannot be safely copied. It never writes the original project. Commands run without shell interpolation, with timeouts and captured logs. It invokes native version, schematic XML netlist export, a reviewed metadata change followed by native reload, and a generated Execute Command job-set run.

Native netlist inclusion differs from BOM inclusion; the comparison checks unexpected native references and records actual memberships, not a false claim that BOM and netlist sets must match. Adapter compatibility gates remain in force. A failed command remains FAILED. Manual checks remain NOT_EXECUTED even when all executable checks pass.

## Human acceptance on a disposable project

Record actual OS/build, KiCad version, Python interpreter, optional SDK version, plugin path and project hashes. Open PCB and schematic from the same managed saved project. Confirm native cross-selection preferences and IPC settings. Test individual and grouped BOM-to-PCB selection, PCB footprint/pad/field-to-BOM selection, then both schematic relay directions. Test focus separately with opt-in zoom; do not mark success just because an action was submitted.

Include repeated sheets, multi-unit components, identical-looking references in different UUID contexts, DNP/excluded parts and a schematic-only component. Verify no incorrect fallback, echo loop, OS focus theft, surprise edit-target selection or disruption of pending inline edits. Test hidden-row reveal/restore, filter preservation, project switch and disconnect/reconnect.

Review/sync supported fields and native variants with editors closed, reopen the actual saved files in KiCad and compare. Confirm BOM-only variants never appear in native variant definitions. Update PCB from Schematic separately and inspect the result. Load the generated native library through KiCad, place a disposable instance and inspect fields/pins/footprint links. Verify warnings for omitted models and unresolved external footprint links.

Run both passing and intentionally failing native job sets; inspect output collection and exit handling. A failed controlled gate must not publish ordinary BOM outputs. Test fresh install/upgrade/uninstall on each OS; old plugin backup belongs outside the scanned action folder. Perform keyboard-only and assistive-screen-reader testing using the tools actually used by the team.

No supported-version badge should be issued until these records are executed and reviewed. The package is not blanket-certified for future KiCad schemas/APIs.
