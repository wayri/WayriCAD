# WayriCAD Trace Refiner

<img src="icon.png" width="64" height="64" alt="Trace Refiner icon">

Remove small routing jogs and redundant straight segments from an open KiCad 10 PCB. Preview the changes, validate them with native KiCad connectivity and DRC, then apply. This tool adjusts existing tracks; it does not route missing connections or tune signals.

![Native Trace Refiner preview](help-workflow.png)

The screenshot uses a disposable routing fixture. Amber and teal show centreline changes; grey is surrounding routing. It is a native window capture, not a result from your board.

## Use

1. Refill zones, then save the PCB and matching project. Save Board Setup changes first so validation uses the intended `.kicad_pro` and `.kicad_dru`.
2. Open **WayriCAD Trace Refiner**. Choose a scope below and optionally restrict copper layers.
3. Set **Maximum displacement** and **Maximum shortening / chain**, both in mm. Defaults are 0.10 mm. These are geometric bounds, not timing or impedance tolerances. Add any tuned or critical net names to **Protected nets**.
4. Click **Preview**. Amber shows original chains, teal shows proposed replacements. Wheel zooms, drag pans and double-click fits. A bounded search may leave routing unchanged.
5. Click **Validate candidate**. The tool serializes detached copies of the current live geometry, copies the matching saved project/rule files, checks native pad/via/zone connectivity, refills candidate zones for DRC and compares before/after native reports. Validation runs in a separate native Python process with cancellation and a six-minute timeout. The live PCB is not edited during validation. Core copper collision/dimension checks are enabled in the disposable validation project even if disabled in your saved settings; the original project is unchanged. Cancellation or any failed check blocks Apply.
6. Click **Apply refinement**. Inspect routing, refill zones and run final KiCad DRC before saving. This window provides **Undo** and **Redo**. Closing it discards that operation history; ordinary PCB Editor Undo is not claimed.

| Scope | What it includes |
|---|---|
| Selected tracks | Selected straight tracks only; selection boundaries stay fixed |
| Selected nets | Nets of selected tracks, vias, pads or parts |
| Whole board | Eligible straight tracks on permitted layers |
| Net filters | Checked net names; search narrows the list without clearing checked choices |
| Net groups | Checked native net classes; combine with a layer filter |

No checked layers means all enabled copper layers. Grouped and locked tracks are always preserved. Net groups here means native **net classes**, not component groups.

## What is protected

- Chain endpoints, pad/via contacts, branch junctions, net ownership, width boundaries and original copper layers.
- Vias, arcs, grouped routing, locked tracks and repeated tuning meanders.
- Native differential-pair names ending in `_P`, `_N`, `+` or `-`, numbered P/N counterparts found on the board, plus editable protected wildcards. Initial wildcards protect common clock, DDR, USB, PCIe, LVDS, RF and CAN names. Names alone cannot identify all design intent: protect any other critical or tuned nets yourself.
- Boards with saved custom length, skew or differential-pair gap/uncoupled constraints are blocked in this first version. It does not infer a safe pair/skew update.
- A baseline with 199 or more findings of any one type is blocked conservatively: potentially capped native reports cannot prove a reliable no-new-findings comparison. Resolve those existing findings first.
- Chains with existing native DRC findings are not changed. New DRC or unconnected-item findings block the entire candidate. Narrow the scope if an otherwise valid proposal shares a batch with an unsafe one.

Geometry generation checks both directions of the original/replacement centreline distance, absolute shortening and self intersections. Native copper checks remain required because centreline similarity does not establish clearance, plane-reference continuity, timing or signal integrity. Necessary routing detours remain if no accepted local replacement exists.

Search is local and bounded: chains longer than 127 segments, loops and exhausted planning budgets remain unchanged. No shove routing, rule relaxation, via movement or automatic differential-pair correction is performed. Whole-board validation can be slow; selected nets or layers give a smaller review.

## Validation

Windows / KiCad 10.0.6: 28 native and geometry tests cover the UI, scopes, endpoint/branch/contact preservation, protected nets, source/rule staleness, clearance rejection and rollback. An extracted PCM installer was tested without source-tree or sibling-plugin imports. [Validation details](../docs/audits/TRACE_REFINER.md).

The public Marble board preview was exercised on 41,044 tracks. Applying its candidate remains blocked by the large existing native DRC baseline; this is not a claim of validated Marble edits.

## Install and compatibility

This is a separate native ActionPlugin, version 0.1.0. Build an independent PCM candidate with `python build_pcm.py --output-dir candidate`, then install `candidate/WayriCAD-trace-refiner-0.1.0-PCM.zip` using **KiCad Manager → Plugin and Content Manager → Install from File**. Restart PCB Editor. The plugin has its own toolbar icon and needs no IPC API or sibling plugin. It requires the matching KiCad CLI for validation.

Windows with KiCad 10.0.6 is the native validation target. Linux/macOS GUI and KiCad 11 are unverified. This source addition is not included in older published suite releases.

KiCad describes [routing and design-rule checking](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html). Review fabrication, tuning and stackup requirements for your board before accepting geometric changes.
