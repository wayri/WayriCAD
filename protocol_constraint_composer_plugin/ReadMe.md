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
reviewed copy. These interface changes are newer than release 3.6.28 and are
currently available in source.

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
