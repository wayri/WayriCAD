# DFM / DFA Studio

Introduced in 4.8.3: **Fab net compare...** provides imported
manufacturing shorts/opens evidence. See [fabrication comparison](FAB_NET_COMPARE.md).
It compares exact terminal partitions, not net names, and never treats a native
PCB reference export as independently reconstructed fabrication copper.

See the [guided offline help](dfm_help.html) and [headless command guide](DFM_CLI.md).
Since 4.8.2, the vendor browser selects an exact service, filters by board layer
count and imports/exports custom profiles without replacing bundled IDs. Save
the complete checklist to retain a custom process across sessions.

Native board loading and geometry extraction run on the GUI thread. A failed
preview does not erase completed CLI evidence; reports disclose that omission.
Failed/cancelled reruns clear old evidence. Saved-board layer preflight applies
to both GUI and CLI runs. Courtyard, mask, silk and routing-end findings can
mark a related engineering requirement FAIL as partial negative evidence;
clean native output never automatically passes the broader manual requirement.

The manufacturing package exposes two separate PCB-editor actions:

- **Manufacturing Readiness Manager** retains the existing saved-project audit,
  project DRC, jobset and release archive workflow.
- **DFM / DFA Studio** checks a saved PCB against a selected manufacturer process,
  stores portable checklists and links native findings to board geometry.

## Manufacturer presets and applicability

The [source catalogue](vendor_catalog.json) currently contains **24 process
presets and 28 manufacturer directory entries**: 23 presets have native rules;
the PCBWay recommendation checklist is manual. These are different coverage
counts: a directory entry without a preset has no runnable numerical rules.
Use **Vendors…** to inspect coverage and source references. PC Process and
Krypton Solutions, among others, still require supplier confirmation; another
manufacturer's limits are never substituted for theirs.

Choose the exact service, layer count, copper specification and any required
material, thickness or finish. Copper can mean starting or finished foil,
depending on the source: read the process notes on the confirmation control.
The selected context explicitly records starting copper, finished copper or the
manufacturer's order-option weight. An order option is not silently converted
to either physical basis. Required inner-copper weights are recorded separately.
Confirm the process against the board and quotation. Unknown or incompatible
scope prevents native-rule compilation. These presets are screening inputs,
not supplier approval or a claim of complete coverage of all major vendors.

Numerical rules link to their published source, access date and process scope.
Recommended dimensions retain warning severity. Conflicting rounded units or
documents are recorded in the notes instead of silently choosing a less
restrictive number. Supplier confirmation is still needed for the actual order.

## Saved checklists

**Save checklist…** retains the exact profile, selected process, latest run,
manual evidence and waivers in a versioned JSON file. **Load checklist…** also
accepts a sourced vendor-profile JSON file. Source, profile and process changes
make old results stale. A waiver remains separate from the measured status and
never turns a failed check into a pass.

The common engineering checklist includes routing, holes/vias, solder mask,
silkscreen, assembly placement, stencil/paste, thermal balance, test/rework
access, population and panelization work items. These are explicitly manual
where an automatic evaluator is not implemented or process evidence is missing.
They are not additional numerical requirements attributed to the manufacturer.
Attach measurements or supplier evidence, then explicitly record a manual
evaluation. A note by itself does not mark a requirement passed.

## Native checks and background operation

**Rule preview…** shows the exact custom-rule text before running. The current
compiler supports sourced `track_width`, `clearance`, `hole_size`,
`annular_width` and `edge_clearance` constraints in millimetres. Additional
conditions, unverified sources and other backends remain omitted with reasons.
Duplicate unconditional constraints in imported profiles are rejected because
KiCad would use the last matching constraint and could hide an earlier limit.
The native `clearance` constraint covers electrical clearance between different
nets. It does not establish every same-net fabrication gap or copper-sliver
requirement; those remain separate checklist items.

**Run vendor DRC / DFM checks** copies the saved PCB and matching project into
one temporary workspace, substitutes the previewed vendor rules there and runs
KiCad's native JSON DRC. The original custom rules are hashed but **are not
applied in this vendor-only copy**. Relevant native check providers are set to
error and saved DRC exclusions cleared only in that copy, so an ignored project
check cannot suppress a vendor violation. The evidence records these overrides;
the source project's severities and exclusions remain unchanged.
Run ordinary project DRC separately through
KiCad or the existing Manufacturing Readiness Manager. The evaluator does not
save, refill or alter the source board.

For a manual-only preset, the button explicitly changes to **Run project DRC ·
manual vendor checks**. This mode preserves the saved project rules in the
private copy, and all vendor-specific requirements remain manual/unknown; it
does not imply that the manufacturer supplied runnable numerical limits.

**Check after saved changes** is optional. A window-owned timer watches saved
PCB/project/rule metadata and schedules one worker, coalescing further saves.
It does not install a service or continuously run full-board DRC while routing.
Unsaved editor changes are outside the checked snapshot. Cancel and window close
terminate the active owned CLI process. Late or changed-source results are
discarded; stale board highlights and exports are cleared.

## Visual findings and cross-probing

Filter by requirement text, status, reference/net text or check family. Select a
row to highlight its saved-board UUIDs and display the native measured/required
description, sources and attached evidence. Click linked copper to select its
finding, use **Focus** or **Fit**, pan with the middle mouse button and zoom with
the wheel. **Cross-probe in PCB** resolves identities in the originating editor
and checks the saved PCB hash; unavailable or stale navigation reports an error.

Straight-track width arrows use the native trace width and a perpendicular
dimension at its midpoint. Distances between native DRC marker coordinates are
not interpreted as copper clearances. Pads, arcs and clearance gaps retain
KiCad's reported dimensions until exact overlay geometry is available.

## Reports

**Export report…** offers HTML and PDF with a compact lossless PNG board view,
all requirement families, complete native findings, process selections and a
paired JSON evidence file. Screen filters do not remove report requirements.
The exporter checks profile/process consistency and all saved inputs again
before publishing the output set. Loaded/saved checklist paths and native design
files are protected from being overwritten by report sidecars.

## Validation scope and limitations

Native KiCad **10.0.6 / Python 3.11** known-answer fixtures proved a clean
0.6 mm route passes and a 0.3 mm route fails a 0.5 mm custom minimum. Native JSON
retained four failing UUIDs and coordinates. Original PCB/project/custom-rule
hashes stayed unchanged. Native regression fixtures also retain failing track-width, clearance, hole-size,
annular-ring and edge-clearance findings when source project providers are ignored;
the original settings stay unchanged.
Hidden native controller checks cover worker completion, cancellation, stale
results and nondefault process save/load. They do not prove
visible editor workflow acceptance or live IPC cross-probing. KiCad 11 acceptance
remains pending.

Automatic full assembly-process, 3D collision/tool access, solder-joint,
stencil-process and every manufacturer's private quotation rules are not
implemented. Unknown/manual checks are not passes. Read the original capability
documents and resolve incomplete process data before ordering fabrication.
