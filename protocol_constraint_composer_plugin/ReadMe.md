# WayriCAD Constraint Studio

<img src="resources/icon-96.png" width="72" height="72" alt="Constraint Studio icon">

| Start here | Link |
|---|---|
| Download and install | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation guide](../docs/INSTALLATION.md) |
| First use | [Getting started](#getting-started) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| Command line | `wayricad tools run protocol-constraints -- --help` |

CLI scope: JSON constraint composition; reviewed project apply remains separate. The unified command requires the [suite CLI installation](../docs/TOOL_CLI_CATALOGUE.md); installing this PCM plugin alone does not install the complete CLI suite.

Inspect saved KiCad rules and prepare grouped design intent in a saved-project
workspace. Edit individual rules in KiCad 10's **Tools → Design Rule Editor**;
edit netclasses and board-wide settings in **Board Setup**. Studio retains protocol
presets, clearance matrices, reusable sets, BGA managed regions and scoped layer
profiles with via rules. Studio changes stay staged until you export and apply a
reviewed copy. These interface changes are included in release 3.6.29.

## Getting started

1. Save the PCB and Board Setup in KiCad, then open **WayriCAD Constraint Studio**.
2. Select a rule in **Rule overview** to inspect its saved dimensions and scope.
   Create or edit individual rules in KiCad, then save and reload Studio. Use
   **Protocol presets** to prepare common buses in Studio.
3. Open **Scope filters**, **Board preview** or **Rule details** when needed.
   The worksheet starts at full width, with these panels closed.
4. Go to **Review & export**. Resolve local errors, inspect the changes, and export
   to a separate empty folder. Run native KiCad syntax checks and DRC on that copy.
5. Click **Open Apply Review**. Close every source-project editor before confirming
   the helper's write. Reopen the project in KiCad afterward.

Apply Review checks source fingerprints and makes backups. Scope colours and local
lint help review your intent; they do not replace native DRC.

## The workspace

| Where | What to do |
|---|---|
| Rule overview | Read minimum, preferred and maximum values, scope and priority. |
| Scope filters | Narrow the table by component, net, netclass, area or constraint family. |
| Board preview | Zoom, pan and select saved objects to inspect a rule's scope. |
| Rule details | Read dimension illustrations, matching feedback and expanded expressions/priority traces. |
| Layer routing profiles | Configure a named protocol/net group for each permitted routing layer. |
| Review & export | Inspect findings, native rules and file differences before applying. |
| More settings & tools | Open matrices, reusable sets, BGA and other specialist workflows. |

A **Clear filter** button remains visible when a scope filter is active, even if its
panel is closed. Undo/redo works across staged edits. **Help / F1** opens the bundled
reference inside the application.

![Current native read-only overview](help-readonly-overview.png)

Actual native fallback window on the public demonstration fixture. Source rules
and generated protocol rules are inspected without editing their cells.
[Overlap audit and validation](../docs/audits/CONSTRAINT_NATIVE_OVERLAP_2026-10-23.md).

![Earlier worksheet with supporting panels closed](help-workflow.png)

![Board preview and illustrated rule details opened](help-rule-panels.png)

These images record the earlier editable worksheet with the public demonstration
snapshot; they are historical and do not show the current read-only overview.
[Capture and validation notes](docs/UI_SIMPLIFICATION.md).

## Set up layer routing

1. Open **Layer routing profiles**. Create one instance for each bus or group,
   such as CAN1, CAN2 or DDR Data. Select exact nets or an existing netclass.
2. Add each signal layer, its reference plane(s), trace width and differential gap.
   Expand **Compare layer geometry** to compare the diagrams at a common scale.
3. Optionally define a via type, diameter, drill and layer span. Review the saved
   stackup, reference continuity and fabrication limits.
4. Review and stage the profile, then export/apply it using the workflow above.
5. In KiCad, use netclass/rule sizing and turn **Auto track width** off. At a via,
   finish the route and start a new route on the destination layer to use its profile.

KiCad 10 keeps one width during an active route. Studio does not resize existing
copper or automatically choose a via type. Differential nets must use names KiCad
recognizes as a pair. Recheck profiles after changing the stackup or net membership.

[Detailed layer-routing guide](docs/LAYER_ROUTING.md) · [Offline help](help.html)

## Save, refresh and recover

Studio reads saved geometry, not unsaved editor changes. A clean workspace refreshes
when Studio regains focus; **Reload saved board** refreshes it explicitly. Export or
undo staged changes before reloading.

If the visual page stops responding, use **Open native overview · recover workspace**
above it. The same staged work stays available in the native inspector. Missing replies
time out without replaying edits. If WebView cannot start, Studio falls back to the
native inspector and displays the error.

## Supported scope and limits

- The packaged 34-constraint catalog remains available as reference data and for
  inspecting generated rules. Author general rules in KiCad's graphical or custom
  rules editor.
- Presets and width estimates need review against the actual stackup, devices and
  fabricator. A named reference layer alone does not prove plane continuity.
- Condition matching is a conservative subset. Unknown matches stay unknown;
  illustrations are not effective-rule or impedance certification.
- Windows/KiCad 10 native WebView checks are recorded in the UI validation notes.
  Other hosts, DPI settings and KiCad 11 still need acceptance checks.

## Installation and source development

Install the WayriCAD **protocol-constraints** PCM package. Its ID stays
`com.github.wayri.wayricad.protocol-constraints`. Do not install the original
standalone Constraint Studio package beside it.

Source launch with KiCad's Python and wxPython:

```powershell
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m protocol_constraint_composer_plugin.studio_ui C:/Projects/Example/board.kicad_pcb
```

[Integration details](docs/INTEGRATION.md) · [Full development guide](docs/USER_GUIDE.md) ·
[Feature status](docs/FEATURE_STATUS.md)

Constraint Studio 0.3.1 is included with the source owner's GPL-3.0 authorization.
[Source provenance](SOURCE_PROVENANCE.json) retains archive hashes; original notices
remain in the bundled license files. Optional signing needs `cryptography`, and
NumPy accelerates the optional solver; these are not installed automatically.

## Implemented methods, numerical scope and evidence

| Method | Inputs and outputs | Implementation, evidence and limits |
|---|---|---|
| Rule parsing, preservation and lint | Saved `.kicad_dru` S-expressions become ordered rule/constraint objects; unchanged rules retain raw unsupported expressions while edited supported records emit normalized text. | [`RuleDocument`, `rule_from_node`, `lint`](constraint_studio/model.py). Numeric expressions use a bounded arithmetic evaluator rather than `eval`. Local lint detects structural/value issues but does not execute KiCad's complete rule engine. |
| Conservative condition expressions | Object/property/function predicates are parsed into an allowlisted expression tree and combined explicitly. | [`expressions.py`](constraint_studio/expressions.py). Unsupported constructs remain unknown for matching; preview colours and counts are therefore review aids, not effective-rule proof. |
| Protocol-name presets | Explicit net names are matched against preset regular expressions and compiled into managed rule blocks delimited by stable markers. | [`detect_protocols`, `generate_rules`, `merge_managed_rules`](analysis.py). Detection is name based; it does not identify an electrical protocol from waveforms or connectivity. Only the managed block is replaced. |
| Profiles, matrices and review provenance | Typed bindings are validated/substituted into reusable rule profiles; matrix CSV and review records are fingerprinted and retained with workspace metadata. | [`compile_profile`, `install_profile`, `matrix_from_csv`, `record_review`](constraint_studio/engineering.py). A recorded review is provenance, not an independent technical approval. |
| Board-context and region guards | Saved footprints/areas are fingerprinted. Courtyard edges are chained into closed contours, transformed to board coordinates and converted to nested region scope terms. | [`BoardContext`](constraint_studio/board.py), [`stage_regions`, `check_regions`, `rebuild_regions`](constraint_studio/courtyards.py), and [`linked_areas.py`](constraint_studio/linked_areas.py). Unsupported/open/self-intersecting geometry is refused; copied/attached regions are invalidated when guarded source geometry changes. |
| Topology path budgets | Board endpoints plus explicitly declared two-terminal bridges form a bounded series path; a total delay budget less margin is allocated to named segments. | [`series_path`, `compile_path`](constraint_studio/topology.py). This follows declared connectivity and bridge rules only; it is not timing simulation and active components require separate modelling. |
| Routing-profile screening | Exact nets/netclasses, saved stackup layers, reference-plane names and via geometry are checked against entered layer profiles and fabrication limits. | [`estimate`, `issues`, `install`](constraint_studio/routing_profiles.py). Width/delay estimates and reference-name continuity are advisory; they do not prove plane continuity, impedance or routability. |
| Quasi-static field estimate | A rectangular-grid finite-volume stencil solves `div(epsilon grad V)=0` with Dirichlet boundaries by diagonally preconditioned conjugate gradients. A dielectric and vacuum solve derive capacitance, effective permittivity, delay and impedance. | [`electrostatic`, `uniform_line`](constraint_studio/field_solver.py). It supports zero-thickness uniform microstrip/symmetric stripline and odd-mode pairs in a finite grounded box; no loss, dispersion, roughness, soldermask, vias or 3-D discontinuities are modelled. [`convergence`](constraint_studio/field_solver.py) checks two meshes and an expanded domain with heuristic 2% indicators; `signoff` is always false. Analytical/convergence checks are included in [`acceptance.py`](constraint_studio/acceptance.py). |
| Snapshot export and guarded apply | Workspace state includes rules, project JSON, saved board text, guards and metadata. Export writes a review bundle with original hashes; apply verifies originals and atomically replaces supported files after editor-closure confirmation/backups. | [`Workspace`](constraint_studio/workspace.py). Staged output must still pass native KiCad syntax/DRC. Workflow and saved-refresh contracts are exercised in [`test_workflows.py`](tests/test_workflows.py) and [`test_saved_board_refresh.py`](tests/test_saved_board_refresh.py). |
| Native validation | `kicad-cli pcb drc` is run against the staged board and its return status/report retained. | [`native_drc`](constraint_studio/validation.py) and [`acceptance.py`](constraint_studio/acceptance.py). This is native-backend evidence for that snapshot, not certification. |

### Research and format references

- KiCad's official [custom design rules documentation](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#custom_design_rules) and [board file format](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/) are dependency/format references for rule and geometry semantics.
- KiCad's [command-line documentation](https://docs.kicad.org/10.0/en/cli/cli.html) defines the native DRC backend used after staging.
- M. R. Hestenes and E. Stiefel, [“Methods of Conjugate Gradients for Solving Linear Systems”](https://nvlpubs.nist.gov/nistpubs/jres/049/jresv49n6p409_a1b.pdf), *Journal of Research of the National Bureau of Standards* 49(6), 1952, is the primary algorithmic background for the linear solver. The project's stencil, finite box, capacitance extraction and convergence policy remain implementation-specific and require independent validation.
