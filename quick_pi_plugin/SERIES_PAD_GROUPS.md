# Explicit current-pad groups in series studies

The **Series path editor** supports an explicit reviewed current-terminal pair
for components with more than two pads. Choose **Add explicit pad pair…**, pick
the incoming/outgoing pads and review the resistance/RL or forward-drop model
shown in the editor. The review checkbox confirms that choice. A switch,
controller or transistor control loop is not inferred from a footprint.

For each side, optionally check **Include all other same-net … pads on this
component**. The editor includes only pads owned by the exact same footprint
UUID on the exact same net as that side's selected anchor. Gate/control pins on
other nets remain excluded. Source and sink anchors have equivalent opt-in
all-peer checkboxes. Leave these unchecked to retain single-pad electrodes.

Each reviewed group becomes one ideal equipotential electrode in the existing
DC FEM. The load current is the total for the whole sink group; the component
R/RL/drop model is stamped once between its two electrode groups. Copper
conductance determines the current distribution. No equal per-pad current split
or duplicate per-pin load is assumed. Contact/package parasitics beyond the
entered model remain unmodeled.

The parser and service reject ambiguous labels, UUID/label aliases for one pad,
wrong-owner or mixed-net groups, omitted anchors, pads assigned to several
electrodes, and overlapping mesh contacts. Automatic parallel-part detection is
disabled through explicit multi-pad stages. This feature covers a reviewed DC
current path; it does not establish device bias, switching waveforms or thermal
behavior. Grouped series electrodes do not enable multisink, power-regulation,
3D, resistive-load or current-sweep series workflows.

Save/load path JSON and CLI `--series-file` retain the groups. The shared intake
is `series_editor.parse_saved_path(data, inventory)`. Source and sink singular
anchors remain present for display; plural metadata belongs to the series-path
contract. Example values below illustrate the format only:

```json
{
  "schema": 1,
  "source": "J1.1",
  "sink": "U1.1",
  "source_terminals": ["J1.1", "J1.2"],
  "sink_terminals": ["U1.1", "U1.2"],
  "branches": [
    {
      "reference": "Q1",
      "from_pad": "Q1.1",
      "to_pad": "Q1.3",
      "from_pads": ["Q1.1", "Q1.2"],
      "to_pads": ["Q1.3", "Q1.4"],
      "model": "100mΩ"
    }
  ]
}
```

The example excludes Q1.5. Actual pad groups and operating-state assumptions
must be reviewed against the saved design. Inductance fields require explicit
H units such as `1mH`, `10nH` or `1pH`; `1m+1p` is ambiguous and rejected.

## Automatic path discovery

The series editor separates **Auto**, **Console** and **Bundle** views. Choose
source and sink pads, open **Auto**, then **Find paths**. Select a candidate
net route and a stage. Only that stage's review is expanded: select alternative
components or parallel members, review incoming/outgoing pins, and enter each
model. The embedded **Diagram / Details** preview shows the complete validated
path, including parallel branches and pin groups, without opening a second
window. Diagram reuses the native power-tree canvas with zoom, fit and pan;
Details retains the tree of stages and pins. The caption explicitly says
**Topology only**: no solved voltage, current or power is fabricated. Invalid model,
endpoint or console edits clear both views and disable Run / Save; old branches
cannot silently substitute for an invalid active draft.

**Correct stage…** opens component and current-pin dropdowns for the selected
stage's existing saved net pair, plus model type and expression. Changing the
component clears the model and both pin choices: transistor/IC current pins
and device states are not assigned automatically. A model-only edit preserves
reviewed groups and parallel parts. Changing pin groups or replacing a bank
requires explicit confirmation. Cancel leaves the original path unchanged.
**Correct stages / explicit path** retains ordered add/remove/reorder, explicit
pair entry and parallel review for paths outside automatic discovery.

**Console** accepts the same bounded `run pi` grammar with pad suggestions.
Valid typing updates the tree; **Use manual path** applies it to the ordered
editor. The unchanged parser checks net continuity and model units. Switching
modes retains drafts but Run / Save validates the selected mode, not a hidden
previous command. Source/load-only same-net commands remain in the ordinary
single-net workflow, not a series solve.

**Bundle** retains named independent batch setups, each with its own voltage,
current, groups and models. **Add current path** captures the active Auto or
Console path; it does not copy whichever bundle row happens to be selected.
Selecting a saved case previews it, and **Edit selected** reopens it in Auto
using the same review/correction workflow. Update selected writes the reviewed
active path back to that case. Refresh clears selection, requiring an explicit
row selection before Update / Remove. Batch setup files, source-revision
guards, path JSON and simulation/report exports retain their existing formats.
The single-path Run button is disabled on the Bundle view; **Run batch…** uses
the existing independent-case solver. Cancel/close retains the in-memory draft,
including Console text and mode, but does not start a solve.

Each stage lists the components spanning
that saved net pair as a proposed parallel bank, with incoming, outgoing and
excluded pin numbers. Uncheck unused parts or pins and enter each component's
model. Bare resistor values can be suggested from their saved Value field;
other models start blank. Inductor value is not DCR. Use `100mΩ`,
`5mΩ+10nH`, `0.7V` or the existing diode expression. Parallel stages require R/L
models. **Use reviewed path** validates the inputs and returns them to the normal
series editor; it does not run the solver. The ordinary draft, setup, path and
simulation save/load workflows retain the reviewed topology and pin groups.

Default discovery considers R, L, FB, F, D, Q, SW and NT references. **Include
other device types** permits additional component classes for explicit terminal
and state review. Source/load footprints are never treated as intervening
conductors. No bias, gate behavior, converter action, copper continuity or
electrical parameter is established by a saved net-name match.

Search is bounded to 24 candidate routes, 16 stages and 5,000 expansions; the
dialog reports truncation. It avoids repeated nets and footprints. Every device
in a proposed bank is reserved for that candidate, even if later unchecked, so
some multifunction routes can be omitted. Discovery is a starting point; manual
and explicit pad-pair entry remain available.

Read-only automation:

```text
wayricad-pi Example.kicad_pcb --infer-series --source J1.1 --sink J2.1 --output candidates.json
wayricad-rlc infer-series Example.kicad_pcb --start J1.1 --end J2.1 --output candidates.json
```

The JSON contains suggestions, not a solved circuit or a ready `--series-file`.
The PI command returns 3 when no route is found. RLC discovery uses the same
topology engine; its numerical path analysis continues to measure individual
copper segments. AC, transient, electrothermal and thermal tools keep their
existing model boundaries; they do not acquire an unsupported component solver.
