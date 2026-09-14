# WayriCAD Embed3D 0.4.1 — host acceptance checklist

**Run on a disposable project. These are checks to perform, not completed results.** Record KiCad version, OS, monitor scale, Python/wx versions, source/output hashes and errors. The build environment did not execute native KiCad/wx acceptance.

## Install and main window

Install the PCM ZIP through Install from File with the PCB Editor closed. Restart and confirm the menu/action opens **WayriCAD Embed3D 0.4.1 · Design assets**, not the old model-only heading. Confirm the approved PCM/toolbar/dialog icons, light/dark appearance and no duplicate manual plugin.

Open at 100%, 150% and 200% scaling where available; shrink the window to the allowed minimum and expand/collapse Options. Confirm all five action buttons plus Apply remain reachable in the fixed footer, and source/destination fields, the matrix and preview remain scrollable. Test keyboard focus/Space toggles, Escape cancellation and empty/blank PCB operation. Do not infer this from the stand-in UI tests.

## Matrix and scope

Use a board and schematic containing R1/R2 sharing one symbol/footprint, U1 with several units, a component without models, a schematic-only component and a board-only mechanical part. Check global three-state indicators, independent type cells, blank unavailable cells and actual component details. Search for R1, leave R2 checked offscreen, and confirm the count/preview includes R2. Clear All types, check one cell, and verify Embed checked selects only it. Verify Embed all explicitly includes every available asset without silently changing the ordinary matrix choices.

Use a duplicate reference and conflicting board UUID path; confirm the tool does not silently merge the wrong components. Reused child-sheet files should show a scope warning. Change a source, path or checkbox after preview; Apply must be disabled until a new preview is built.

## Native footprint/model acceptance

Use a stock KiCad resistor, capacitor, IC and user library footprint. Include model paths through KICAD10_3DMODEL_DIR, a custom variable, a library-relative file, Unicode/spaces and an old-version variable. Test a deliberate unresolved model that is unchecked: symbol-only operations should work; selecting that model must stop with its reason.

Set non-default XYZ scale/rotation/offset including negative values, multiple model entries, hide and opacity. Place one footprint rotated and one on the back side, with pads on nets and copper tracks. Selectively embed models and inspect the copied board in the 3D Viewer; save/reopen and verify all transforms and model bytes remain correct. Unselected objects and board copper/net geometry must match.

Select only a footprint. Confirm an actual reusable definition is attached and a local library is generated when enabled, but unchecked external models were not newly embedded. Open the normalized library footprint and compare front/back orientation handling, pad coordinates, fields and 3D appearance. Select footprint + model and verify standalone `.kicad_mod` portability without access to the original model folder.

## Native schematic acceptance

Use two components sharing one cache definition; check only one Symbol cell. Embed with local links, reopen the new schematic and confirm only the checked library ID changed, both still draw correctly, and the unchecked cache key remains. Verify multi-unit symbol naming, body styles, pins, fields, properties, instance UUIDs and wires. Include an edited native `lib_name` override and a child sheet.

Repeat with local links off: archive exists but original symbol library IDs remain. Verify the saved root and children load with KiCad 10 and the optional CLI netlist check runs. Do not call a netlist parser check ERC/electrical equivalence. Native caches must remain after every external relink/prune.

## Separate and combined extraction/relink

Unbundle only models, only footprints and only symbols to separate new asset roots. Check actual bytes/files and verify the original PCB/schematic hashes are unchanged. Test all three together, including an ordinary non-packaged PCB using As placed normalization.

Then use the single Relink button on the extraction root. Inspect model paths, selected symbol IDs, selected footprint IDs and both project library tables in one new output directory. Open its libraries and verify the project-specific footprint view uses the correct model folder. Repeat the same selections with Unbundle & relink; it should produce the equivalent checked scope in a single new design copy.

Move asset + new design folders together without changing their relative relationship, temporarily deny access to original libraries/models, and inspect the result. On Windows cross-drive destinations use Absolute paths; relative mode must fail rather than invent a portable link. Existing aliases must not be repointed; a generated suffix is acceptable.

## Removal, freshness and failure

With Remove redundant attachments off, verify existing embedded data is retained. With it on, select only R1; verify R2's archive/model references and native schematic caches remain. Unrelated arbitrary embedded attachments must survive. Test a shared model and a retained archive that still needs it.

Edit a source file, extracted model, library or manifest after preview. Apply/Relink should stop, not overwrite. Try an existing output directory or conflicting extraction contents; differing files must not be overwritten. A forced native validation error during a combined action must leave originals untouched and no published final design, though verified extracted assets can remain.

Keep `WayriCAD Embed3D-originals`, manifests and reports until acceptance is complete. Review schematic Footprint assignments deliberately before Update PCB from Schematic; symbol ID relinking does not synchronize those assignments. Run DRC/ERC separately after any chosen library updates.

## Retained advanced tools

The old model/live-board and supplied-library tools remain under Options. Test their native undo/redo and API object lifetime separately; passing new saved-copy checks does not validate old live mutation. Save their live changes before returning to the new workspace and rescanning.

## 0.4.1 scan/ownership regression — run on the actual host

Open the updated window and confirm version 0.4.1. Scan a saved board with at least two footprints (one with a model and one without). Confirm both components appear with no schematic selected. Clear all global asset selections, then rescan: both rows must remain, with choices preserved. Check only 3D models: this must not hide the no-model footprint. Select the root schematic and scan again: Symbol cells should become available for matched components.

Search for a nonexistent reference: the window must say that the search hides the scanned components. Clear the search and confirm rows return. Test an invalid schematic path and confirm a visible error, disabled action buttons, and an available Save scan diagnostics button. Restore the correct path, rescan, preview a small operation and verify it in a copied design. Close/reopen the plugin several times to exercise model destruction and re-creation; it must not invalidate the view or crash KiCad.
