# Reviewed power tree

The native editor records a small, explicit power-intent graph:
**source → rail → DC/DC or LDO → rail → load**. A rail has its own saved
net, return net, signed voltage in V, and declared isolation domain. A negative
rail keeps its negative voltage relative to that return. An isolated converter
has separate input/output rail references and domains. Arrows describe energy
flow; they never short nets, merge ground references, or insert resistors.

Select a diagram node or the node dropdown, edit its fields and click **Apply
node edits**. Add/delete nodes and energy links below the diagram. Review each
node and each connection explicitly. **Save draft…** retains incomplete inputs
and unreviewed candidates. **Validate review** checks the complete intent;
**Use reviewed tree** accepts only a complete reviewed graph. **Load tree…**
checks saved net/footprint identities against the current inventory. This editor
does not modify the PCB or existing solver requests/results.

Board suggestions are evidence for review. Supply-like net names suggest rails
with unknown voltage, return and domain. Explicit saved value descriptions such
as `LDO`, `buck converter` or `isolated DC/DC converter` suggest device roles.
Part numbers alone, generic ICs/MOSFETs, resistor values, net proximity and a
part's connected net list do not establish converter behavior or power direction.
No suggested item or connection is automatically marked reviewed.

An enriched Quick PI terminal inventory may include `component_properties` from
saved footprint fields. Supported fields are `QuickPI:Role` (`source`, `load`,
`dcdc`, `isolated_dcdc`, `ldo`), `QuickPI:InputNet`, `QuickPI:InputReturn`,
`QuickPI:InputDomain`, and corresponding `OutputNet`, `OutputReturn`,
`OutputDomain`. An input/output net pair produces a candidate energy link only
when both nets actually occur on that footprint. Missing values stay unknown.
Saved footprint fields are included in the native inventory. If those fields are absent, manual review is needed.

## JSON interface

`power_tree.infer_power_tree(inventory, source=None)` returns a schema-1 draft.
`validate_power_tree(document, require_reviewed=False, inventory=None)` returns
a detached validated document. `load_power_tree(path, **validation)` and
`save_power_tree(path, document, **validation)` use the same validation.
These functions import neither wx nor native KiCad modules and can serve CLI
callers. `source` retains provenance such as `source_sha256`; when the supplied
inventory also contains that hash, a changed board is rejected. Without both
hashes, only declared net/footprint existence is checked, not source freshness.

```json
{
  "schema": 1,
  "source": {},
  "nodes": [
    {"id": "supply", "kind": "source", "label": "External input", "reviewed": true, "confidence": "manual", "evidence": ["Reviewed connector input"]},
    {"id": "rail", "kind": "rail", "label": "Negative supply", "net": "-5V", "return_net": "GND", "voltage_v": -5, "domain": "primary", "reviewed": true, "confidence": "manual", "evidence": ["Declared nominal voltage"]}
  ],
  "edges": [{"source": "supply", "target": "rail", "reviewed": true, "evidence": ["Reviewed energy direction"]}]
}
```

## Supported scope and limits

This is a reviewed intent map, not a converter simulation or automatic circuit
extraction. It does not calculate efficiency, losses, dropout, switching
waveforms, regulation, isolation rating, load currents or whole-board power
balance. Converter capability needs independent datasheet/design review. Copper
studies remain separate explicit Quick PI requests.

Graphs are bounded to 256 nodes, 512 edges and 2 MiB JSON. Energy flow must be
acyclic and alternate devices/rails. One input and one output per converter are
supported, with many loads allowed on a rail. Combining feeds, multi-output
converter coupling, feedback edges and bidirectional operation need separate
models; they are rejected or must be recorded as separate clearly declared
intent paths. A non-isolated converter cannot change the declared reference or
domain; isolated primary/secondary references and domains must be separate.
The same saved electrical net cannot be declared in two isolation domains.

## Command line

```text
wayricad-pi C:/Projects/Example/board.kicad_pcb --infer-power-tree --output power-tree-draft.json
wayricad-pi --power-tree power-tree-draft.json
```

Inference writes an unreviewed draft, never a solver connection. Validation can
check a draft without solving or modifying the board. The native editor's
**Use reviewed tree** action requires the complete reviewed intent.
