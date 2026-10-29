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
