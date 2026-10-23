# WayriCAD Trace Refiner

<img src="icon.png" width="64" height="64" alt="Trace Refiner icon">

Remove small routing jogs or center off-center track contacts on an open KiCad 10 PCB. Choose **Routing jogs** or the separate **Pad / via centering** tab, preview the changes, validate them with native KiCad connectivity and DRC, then apply. This tool adjusts existing tracks; it does not route missing connections or tune signals.

| Start here | Reference |
|---|---|
| [Latest release](https://github.com/wayri/WayriCAD/releases/latest) | [Install](../docs/INSTALLATION.md) · [Suite CLI](../docs/TOOL_CLI_CATALOGUE.md) |
| [Preview → Validate → Apply](#use) | [Command line](#command-line) |
| [Compare old and new routing](#comparing-proposed-routes) | [Protected geometry](#what-is-protected) |
| [Center pad/via contacts](#center-pad-and-via-contacts) | [Troubleshooting](#troubleshooting) · [Offline help](help.html) |

## Native workflow: compare, validate and apply

![Validated routing shown side by side](help-validated-comparison.png)

Actual Windows / KiCad 10.0.6 window on a disposable two-pad fixture. Amber is
the original route; teal is the proposed replacement. Five segments become one,
with 0.1243 mm shortening, within the selected 0.20 mm displacement and 0.30 mm
shortening limits. Native validation reported unchanged terminal connectivity
and **zero new DRC findings**; two baseline findings remained in both reports.
The saved source was unchanged during preview and validation.

![Successful refinement with Undo available](help-applied-refinement.png)

After explicit Apply, the proposal table is cleared and both comparison panes
show the current, refined board context. The native status confirms Apply and
offers Undo. This run retained the first source track UUID, checked native
connectivity, and restored all five original tracks with Undo. These are source
window checks on a synthetic fixture, not a claim that a user board or installed
editor session was qualified. See [capture provenance and checks](../docs/audits/ROUTING_README_SCREENSHOTS_2026-10-23.md).

### Earlier routing and review examples

![Native Trace Refiner preview](help-workflow.png)

The screenshot uses a disposable routing fixture. Amber and teal show centreline changes; grey is surrounding routing. It is a native window capture, not a result from your board.

![Proposal metrics and focused review](help-review.png)

The 0.2.0 native fixture capture shows per-chain metrics, click-to-focus highlighting and proposal exclusion. Neither screenshot is a result from a user board.

## Use

1. Refill zones, then save the PCB and matching project. Save Board Setup changes first so validation uses the intended `.kicad_pro` and `.kicad_dru`.
2. Open **WayriCAD Trace Refiner**. Choose a scope below and optionally restrict copper layers.
3. Set **Maximum displacement** and **Maximum shortening / chain**, both in mm. Defaults are 0.10 mm. These are geometric bounds, not timing or impedance tolerances. Add any tuned or critical net names to **Protected nets**.
4. Click **Preview**. Amber shows original chains, teal shows proposed replacements. Wheel zooms, drag pans and double-click fits. A bounded search may leave routing unchanged.
5. Click **Validate candidate**. The tool serializes detached copies of the current live geometry, copies the matching saved project/rule files, checks native pad/via/zone connectivity, refills candidate zones for DRC and compares before/after native reports. Validation runs in a separate native Python process with cancellation and a six-minute timeout. The live PCB is not edited during validation. Core copper collision/dimension checks are enabled in the disposable validation project even if disabled in your saved settings; the original project is unchanged. Cancellation or any failed check blocks Apply.
6. Click **Apply refinement**. Inspect routing, refill zones and run final KiCad DRC before saving. This window provides **Undo** and **Redo**. Closing it discards that operation history; ordinary PCB Editor Undo is not claimed.

### Center pad and via contacts

1. Open **Pad / via centering**. Choose selected tracks, selected nets, net filters/classes or the whole board, and optionally restrict layers.
2. Set **Maximum contact centering shift**. The initial limit is 0.25 mm; the permitted range is greater than zero and at most 2 mm. This is a movement bound, not permission to bridge a gap or ignore clearance.
3. Click **Preview**. The proposal moves an eligible straight-track endpoint to the center of an unambiguous same-net pad or via it already contacts. Pads, vias, footprints, layers and widths remain fixed. Already centered contacts need no change.
4. Inspect the amber/teal overlay and preservation reasons. Centering can increase trace length; the signed **Shorter mm** column is negative when it does. Routing-jog displacement and shortening controls do not govern this separate mode.
5. Click **Validate candidate**, then **Apply contact centering**. Apply remains blocked until native terminal connectivity and before/after DRC checks succeed. Undo/Redo uses the same source-bound history as jog refinement.

The native **Track endpoint not centered on via** finding is a repair target for this mode. Validation enables that rule in disposable copies, verifies the exact reviewed track/via contact and requires the candidate to remove the finding. Other affected-track errors still block Apply. Copied project/custom rules are preserved during validation serialization.

This is endpoint centering, not a general unconnected-net repair. Ambiguous contacts, uncertain pad geometry, branch/interior contacts and protected or detected tuning routing remain unchanged. A native DRC marker can have other causes; inspect the reported reason rather than assuming every marker is an off-center endpoint.

![Native pad/via centering tab](help-centering.png)

Actual KiCad 10 native window on a disposable two-pad fixture after validation.
The focused preview shows the fixed gold pad and teal centered track; no user
project appears in this capture. The image is stored as opaque RGB without
altering the displayed geometry or results.

| Scope | What it includes |
|---|---|
| Selected tracks | Selected straight tracks only; selection boundaries stay fixed |
| Selected nets | Nets of selected tracks, vias, pads or parts |
| Whole board | Eligible straight tracks on permitted layers |
| Net filters | Checked net names; search narrows the list without clearing checked choices |
| Net groups | Checked native net classes; combine with a layer filter |

No checked layers means all enabled copper layers. Grouped and locked tracks are always preserved. Net groups here means native **net classes**, not component groups.

### Choosing the bounds

Start with a few selected tracks or one net and inspect the preview before expanding the scope. A 0.03 mm jog can fit inside a 0.05 mm displacement bound; a 0.005 mm bound will preserve that jog. A larger bound permits more movement, but does not force a change. Both controls must be greater than zero and at most 1 mm.

**Maximum displacement** limits centreline distance in both directions: every part of the original chain must remain near the replacement, and every part of the replacement must remain near the original. This is checked again after rounding to KiCad coordinates. It is separate from the copper clearance enforced by DRC.

**Maximum shortening / chain** limits the total length removed from one connected eligible chain, including all local cleanup windows in that chain. It is an absolute distance, not a percentage or a board-wide budget. A 0.10 mm setting can permit up to that amount on each of several independent chains. Replacements do not deliberately add length; floating-point equality is handled at sub-nanometre scale.

Eligible chains contain connected straight tracks with the same net, layer and width. Each local cleanup considers only a small window, replacing it with a straight segment or a single bend using horizontal, vertical or 45-degree legs. Larger necessary turns remain. Collinear subdivisions can disappear even when there is no visible displacement or meaningful length reduction.

### Reading the result

The table lists proposed chains and explicit preservation notices. A proposal is a complete replacement chain; amber and teal can overlap when only redundant segment boundaries disappear. Pan or zoom to inspect short jogs. A preservation notice describes a condition encountered by the planner, not every track excluded by scope or protection.

An empty preview is a valid result. It can mean the selected routing is already simple, the shortening/displacement budget is too small, a protection applies, or the bounded geometry check cannot prove a suitable replacement. Preview approval does not enable Apply until validation succeeds.

Changing scope, checked nets, classes, layers or numeric inputs clears the preview. Changing the board, its relevant selection, live Board Setup dimensions/net classes or saved project/rule files invalidates source-bound operations. Save the intended settings and preview again rather than reusing an old proposal.

## Review and choose changes

The review table shows the layer, original and proposed lengths, shortening in
mm, and segment counts for each chain. Click a proposed row to focus and
highlight that chain in the preview. This does not change the PCB selection or
copper. Hover over rows for full hierarchical net names and preservation reasons.

Select one or more proposed rows, then **Exclude selected** to leave those chains
unchanged. Preserved notices cannot be excluded as if they were proposals. Every
subset edit clears the old validation evidence and disables Apply: **Validate
candidate** checks the retained subset again. Excluding everything gives a valid
empty preview with no writes. This is useful when a baseline DRC finding belongs
to one proposal and the other chains can be reviewed separately; it never skips
DRC checks for the remaining changes.

## What is protected

- In Routing jogs mode, chain endpoints and pad/via contacts. Centering mode explicitly permits only the reviewed terminal endpoint moves. Both modes protect branch junctions, net ownership, width boundaries and original copper layers.
- Vias, arcs, grouped routing, locked tracks and repeated tuning meanders.
- Native differential-pair names ending in `_P`, `_N`, `+` or `-`, numbered P/N counterparts found on the board, plus editable protected wildcards. Initial wildcards protect common clock, DDR, USB, PCIe, LVDS, RF and CAN names. Names alone cannot identify all design intent: protect any other critical or tuned nets yourself.
- Boards with saved custom length, skew or differential-pair gap/uncoupled constraints are blocked in the current implementation. It does not infer a safe pair/skew update.
- A baseline with 199 or more findings of any one type is blocked conservatively: potentially capped native reports cannot prove a reliable no-new-findings comparison. Resolve those existing findings first.
- Chains with existing native DRC findings are not changed, except a verified **Track endpoint not centered on via** finding for the exact contact reviewed in centering mode. That finding must disappear; other affected-track baseline errors and all new DRC/unconnected findings block the entire candidate. Narrow the scope if an otherwise valid proposal shares a batch with an unsafe one.

Native validation is bound to the exact proposed geometry and settings; modifying a proposal or its replacement tracks after validation blocks Apply. Native operations that mutate and then raise also restore the original routing or report a recovery failure explicitly.

Geometry generation checks both directions of the original/replacement centreline distance, absolute shortening and self intersections. Native copper checks remain required because centreline similarity does not establish clearance, plane-reference continuity, timing or signal integrity. Necessary routing detours remain if no accepted local replacement exists.

Search is local and bounded: eligible chains up to 2,048 segments are supported; longer chains, loops and exhausted planning budgets remain unchanged. Exact collinear fragmentation is collapsed before the bounded local-window search. Mask-opening or local mask-margin changes are chain boundaries, just like width changes. No shove routing, rule relaxation, via movement or automatic differential-pair correction is performed. Whole-board validation can be slow; selected nets or layers give a smaller review.

## Command line

Use the CLI for a repeatable review of a **saved** PCB. It uses the same geometry and native validation gates as the window. It does not connect to an open editor or include unsaved editor changes. Run it with KiCad's native Python, which supplies `pcbnew`; an ordinary Python installation without those bindings cannot run the workflow.

From the repository root, this PowerShell example previews one exact net and writes the JSON review to a file:

```powershell
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m trace_refiner_plugin `
  'C:/Projects/Example/board.kicad_pcb' --net SIGNAL `
  --layer F.Cu --max-deviation 0.05 --max-shortening 0.10 `
  --report 'C:/Projects/Example/refinement-review.json'
```

Without `--validate` or `--output`, the command previews only and prints JSON to stdout. `--report` also saves that report to a new file; an existing report is not overwritten. A report describes a proposal; a preview-only report is not native DRC approval. To check the proposal without creating a PCB:

```text
python -m trace_refiner_plugin C:/Projects/Example/board.kicad_pcb --net SIGNAL --validate
```

To validate and export a separate refined board, first create the destination directory, then run:

```text
python -m trace_refiner_plugin C:/Projects/Example/board.kicad_pcb --net SIGNAL --output C:/Projects/Example/review/refined.kicad_pcb
```

`--output` validates before writing. It creates the new PCB with matching project/custom-rule copies under the new board stem, leaving the source files unchanged. Existing output files are not overwritten. Open the exported project in KiCad, inspect it, refill zones and run final DRC before adopting it. CLI export has no in-window Undo history; the original project remains the review reference.

Center existing contacts on one net and export a separate validated project:

```text
python -m trace_refiner_plugin C:/Projects/Example/board.kicad_pcb --center-contacts --net SIGNAL --max-center-shift 0.25 --output C:/Projects/Example/review/centered.kicad_pcb
```

| Argument | Meaning |
|---|---|
| `BOARD` | Saved `.kicad_pcb` input path |
| `--net EXACT` | Include an exact, case-sensitive net name; repeat for several names. Bus names such as `DATA[0]` are literal names, not wildcards |
| `--netclass NAME` | Include a native net class; repeat for several classes |
| `--track UUID` | Include a specific straight track by native UUID; repeat for several tracks |
| `--layer NAME` | Restrict every scope to a copper layer such as `F.Cu`; repeat for several layers |
| `--max-deviation MM` | Bidirectional centreline displacement bound; default `0.10` mm |
| `--max-shortening MM` | Total shortening bound per chain; default `0.10` mm |
| `--center-contacts` | Use pad/via endpoint centering instead of jog cleanup |
| `--max-center-shift MM` | Endpoint movement bound for centering; default `0.25` mm, range `(0, 2]` |
| `--protected GLOBS` | Replace the default protected-net wildcards with a comma-separated list, such as `*CLK*,*DDR*,ANALOG_*`; quote it in your shell and include every default protection you intend to retain |
| `--validate` | Run native connectivity and before/after DRC without writing a new board |
| `--output NEW.kicad_pcb` | Validate, then export a separate board and matching project/rules |
| `--report FILE` | Save the JSON report to a new file in an existing directory, in addition to stdout |
| `--help` | Display the installed command's usage |

Choose one selector family: `--net`, `--netclass` or `--track`; do not combine those families. Repetition within one family is supported. With no selector, the scope is the eligible whole board. Layer and protection filters apply in every scope. Native differential-pair protection still applies when a net or track is explicitly selected.

The installed console entry point, `wayricad-trace-refiner`, accepts the same arguments when the package and native KiCad bindings are available in that Python environment. PCM installation alone does not add a system-wide console command. Validation/export needs the saved matching `.kicad_pro`, the optional `.kicad_dru`, and matching `kicad-cli`. The module command from a source checkout works without installing a console entry point.

## Troubleshooting

| Message or symptom | What to do |
|---|---|
| No proposed changes | Check selection/scope, layer names and protected nets. Inspect whether the route already has the simplest permitted shape. Try a small, known jog before increasing scope |
| Board or rules changed; operation blocked | Save the intended board and Board Setup, then create and validate a fresh preview. This also applies after edits outside the plugin window |
| Live Board Setup differs from saved project | Save Board Setup/project settings and preview again. Validation must use the same rule dimensions and net classes as the editor |
| A proposed chain already has DRC findings | Fix that routing's baseline findings or narrow the scope to clean chains. The tool does not treat an existing error as permission to move that chain |
| 199 or more baseline findings of one type | Resolve the excessive existing baseline first. Report limits/order prevent a reliable acceptance comparison; equal before/after totals are insufficient |
| New native DRC/connectivity findings | Keep the original routing. Try a smaller displacement, fewer nets or another layer, then validate again. Do not disable the failing check to force acceptance |
| Custom length/skew/pair rule detected | Use native routing/tuning for this constrained board. Removing a rule to obtain approval does not establish safe timing |
| Interior contact, long chain or loop preserved | Leave that topology intact or perform a focused native routing edit. The bounded cleanup intentionally does not solve every route |
| Worker, CLI or native Python unavailable | Use the matching KiCad 10 installation and its native Python/CLI. Restart PCB Editor after installation; `pcbnew` is not supplied by a normal editable Python install |
| Validation cancelled, timed out or worker crashed | Apply remains blocked and the live board stays unchanged. Retry with a smaller scope after addressing the reported runtime issue |
| Output already exists | Choose a new export stem or destination. Keep the old output for comparison; the command does not overwrite it |
| Undo/Redo blocked after another edit | The board no longer matches that transaction's expected state. Do not force the old objects back into the changed board; inspect the current board and use a saved reference if needed |

Apply, Undo and Redo use a grouped object exchange with recovery on failure. If an error explicitly says recovery needs inspection, inspect the current board before continuing or saving; do not assume that operation completed. Closing Trace Refiner discards its window history. Keep a saved project reference for longer-term comparison.

## Validation

Windows / KiCad 10.0.6: native and geometry checks cover the UI, scopes, endpoint/branch/contact preservation, protected nets, source/rule staleness, clearance rejection and rollback. An extracted PCM package was tested without source-tree or sibling-plugin imports; this is distinct from launching a PCM-installed plugin inside PCB Editor. The repository records exact checks and counts in [validation details](https://github.com/wayri/WayriCAD/blob/develop/docs/audits/TRACE_REFINER_0.2.0.md).

The public Marble board preview was exercised on 41,044 tracks. Applying its candidate remains blocked by the large existing native DRC baseline; this is not a claim of validated Marble edits.

## Install and compatibility

The current source/candidate is **0.2.0**. The latest published suite package is
0.1.1 in [WayriCAD 3.6.19](https://github.com/wayri/WayriCAD/releases/tag/v3.6.19);
the public PCM feed is unchanged until the new candidate is published.
Install the new `WayriCAD-trace-refiner-0.2.0-PCM.zip` using **KiCad Manager →
Plugin and Content Manager → Install from File**, then restart PCB Editor.
The plugin has its own toolbar icon and needs no IPC API or sibling plugin. It
requires the matching KiCad CLI for validation.

For source development, `python build_pcm.py --output-dir candidate` builds disposable independent installers in `candidate/`.

Windows with KiCad 10.0.6 is the native validation target. Linux/macOS GUI and KiCad 11 are unverified. Trace Refiner's plugin version is independent of the suite release number; consult its PCM metadata and the suite release notes for the installed version. Historical validation documents below describe their named revisions.

KiCad describes [routing and design-rule checking](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html). Review fabrication, tuning and stackup requirements for your board before accepting geometric changes.

## Faster viewport

The viewport captures display geometry once when opened and refreshes it on
Preview, Apply, Undo and Redo. Pan/zoom/fit repaint cached geometry with batched
drawing and viewport culling, including curved arcs. Run Preview after external
board changes to refresh the display context. Apply still checks the live
source and saved rules; the display cache cannot approve a stale proposal.

## Geometry and performance changes in 0.2.0

Exact straight subdivisions are removed without moving their copper, including
safe unchanged collinear contact geometry. Nonzero jog changes retain the
conservative interior-contact checks. Spatial indexes narrow native contact
queries by net/layer and bounding box; the final checks still use native shapes.
Board fingerprints use KiCad's in-memory serializer rather than temporary PCB
writes. Native transaction membership is reconciled per batch rather than by
rescanning the board for every exchanged segment.

The 2,048-segment limit is per eligible chain, between fixed topology/protection
boundaries. The planner keeps the 30-second overall budget; geometry cleanup
examines at most 1,024 local windows per chain. It can leave valid improvements
undiscovered. Differential pairs, tuning meanders, custom timing/pair constraints
and existing DRC acceptance gates remain protected. This is still geometric
cleanup, not a shove router, timing optimizer or impedance qualification.


## Resize the workspace and find help

Drag the settings/preview divider or the preview/results divider to inspect full routing proposals at a useful size. Settings scroll independently; changing the retained proposal subset still requires fresh native validation.

Open [offline help](help.html) for the workflow and troubleshooting. See [readable windows, panels and tables](../docs/UI_ACCESSIBILITY.md) for resizing, complete-row reading and keyboard controls.

## Comparing proposed routes

The preview's **Compare** selector offers **Overlay**, **Before**, **After** and
**Side by side**. Original routing is amber; proposed routing is teal. Overlay
adds a wider amber comparison outline so coincident paths remain distinguishable;
that outline is a visual aid, not a proposed copper width. The separate views
retain the same zoom, pan and reviewed changes. Repaints use cached geometry.

Native validation and Apply preserve the first source track identity through
the UUID APIs available in the installed KiCad bindings, or through an
independent native clone when setters are unavailable. Identity and uniqueness
are checked before exchanging tracks. Undo, source-hash, connectivity and DRC
checks remain required.
