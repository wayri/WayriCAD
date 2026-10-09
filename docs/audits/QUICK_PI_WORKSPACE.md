# Quick PI compact board workspace

## Scope and behaviour

The 3.6.13 candidate replaces wide forms above the planar board with a fixed-width
Setup sidebar and an adjustable Inspect sidebar. Both panels can be hidden.
Preview, Run, Export and Series remain accessible at the bottom of Setup; More
retains diagnostics, transient and electrothermal studies. Advanced inputs,
the console and model details start collapsed. The window opens maximized.

The native canvas removes graph axes, titles and embedded colour bars. It fits
saved board geometry, keeps equal millimetre scale during resize, supports
direct pan/zoom, and displays a compact ruler. The inspector provides the
calibrated colour range and units. Saved board/component contours and references
remain readable over the field, including KiCad 10's Silkscreen/Courtyard layer
names. Scientific report figures retain their existing presentation.

The solver, field interpolation, exact cell probes, source hashes and load
feasibility checks are retained. INFEASIBLE remains visible, and overload maps
remain explicitly described as requested-load diagnostics.

## Verification on Windows

Checked on Windows with KiCad 10.0.6, bundled Python 3.11.5, wxPython 4.2.2 /
wxWidgets 3.3.2. Portable checks use Python 3.14.2. Test files and captures use
disposable saved boards; no live editor writes or installation were performed.

- Shared regression suite: **397 passed, 73 skipped**, 152 subtests passed.
- Portable Quick PI suite excluding the native production mesher: **202 passed,
  24 skipped**, 173 subtests passed. Skips are not native compatibility passes.
- Focused native UI, renderer, lifecycle and CLI-dispatch suite: **40 passed**,
  11 subtests passed. All sizing/navigation checks use actual wx windows.
- Native sizing checks cover **1320 × 860, 1000 × 680 and 960 × 600**. The canvas
  retains more than 78% of the main panel height. Hiding both panels gives it
  more than 95% of the main panel width. Expanding mesh settings and console
  scrolls Setup without reducing the canvas height.
- Native tests cover result/probe identity, scale/style changes preserving zoom,
  panel restoration after other tabs, source-current/voltage input guards, stale
  exports and unchanged saved PCB hashes.
- All **19 disposable PCM archives** passed schema, independent-runtime, icon,
  action and Python-syntax validation. Source documentation and local images
  passed validation. The new workspace image is bundled in the Quick PI ZIP.
- A fresh process imported only the extracted **Quick PI 3.6.13 PCM** payload
  and KiCad's installed runtime, then opened its actual native window. Board
  contours, calibrated field legend, full-height sizing and panel hiding passed;
  the saved PCB hash was unchanged. No source-checkout imports were required.

A broader native unittest discovery completed 223 tests, with three additional
module-import errors because pytest was initially absent from that interpreter.
Those modules were subsequently exercised with the already-installed pure Python
pytest runner in the successful focused check above. A broad native pytest
attempt encountered a local Gmsh DLL loader exception and was stopped; that run
is not recorded as a pass. The UI work does not change Gmsh setup or solvers.

## Screenshot provenance

The [native workspace capture](../../quick_pi_plugin/help-workspace.png) shows
`demo-power-board.kicad_pcb`, a generated portrait PCB used only for context. The
solved field is an analytical uniform copper plate, **65 × 90 mm**, **35 µm**
thick, with full-height edge contacts, a **5 V** source and **2 A** sink.
Using copper resistivity 1.724e-8 Ω·m gives **0.71149 mV** drop. The illustrated
PCB traces are not the solved plate model. This is UI and known-answer evidence,
not a measured PCB or mesh-convergence claim. No personal paths occur in the
capture and no redaction was required.

Native compatibility on Linux, macOS and other KiCad versions remains unverified.
