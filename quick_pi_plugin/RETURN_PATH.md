# Return-path screen for Quick PI

Quick PI can screen the **saved board's** signal routing against a return net that
the user names explicitly. The screen reads native filled copper-zone polygons,
the selected signal tracks, and signal/return vias. It reports locations where
sampled trace points have no filled return copper on an adjacent layer. At an
evidenced signal layer transition, it also reports when no via on the selected
return net spans the local reference layers within the chosen radius.

For a native `pcbnew.BOARD`:

```python
from quick_pi_plugin.return_path import analyze_return_path

result = analyze_return_path(board, "VCC", ["GND"],
                             sample_pitch_mm=0.25,
                             return_via_radius_mm=2.0)
for finding in result["findings"]:
    print(finding["level"], finding["code"], finding["position_mm"])
```

`collect_board_evidence` and `audit_return_path` are separate entry points for
UI preview and repeatable tests. The evidence and result are JSON-compatible.
The caller should load a saved board if the report must correspond to a saved
revision; reading a live board does not prove that its state has been saved.
The screen never writes to the PCB.

An unfilled reference zone, unsupported arc, or via without routing evidence on
two layers produces an **unknown** finding. A zero-warning result is only a
screening result: point sampling can miss narrower splits, and this check does
not solve return current density, via inductance, plane transfer impedance,
parallel-plane coupling, reference trace continuity, or full-wave behavior.
Inspect the layout and use a qualified field or circuit model where those
effects matter. The selected return net is a design input, not inferred from a
name such as `GND`.
