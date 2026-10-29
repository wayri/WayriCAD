# Quick PI board-first workspace

The default board viewport uses the full window width. Setup and Details are
optional drawers, with their numerical settings and results retained while
hidden. Focus view remembers which drawers were open and their widths. Run,
Files, Fit and Help remain visible. Files calls the same validated setup and
simulation Save/Load actions as the drawer buttons; reports remain separate.

- **Setup:** net search, source/load pads, multipin choices, mesh/material settings.
- **Details:** layers, field metric, calibrated colour legend, losses and probes.
- **Current tuning:** folded by default; expand for numeric current/step controls.
  Ctrl+scroll on solved copper or a sink remains enabled when folded; normal
  scroll zooms. Loading or changing simulation inputs still invalidates results.
- **Fit:** fit the complete board/visible domain with its physical aspect ratio.
  Drag pans, wheel zooms, double-click fits. Source/sink and differential probes
  retain their existing gestures.

The selected field name, limits and units remain in the header even when Details
is closed. Their values follow the same colour scale as live current changes.
On smaller windows the toolbar wraps, and drawer inputs scroll independently.
The board is not stretched or cropped to hide whitespace on portrait designs.

## Native layout checks

Windows, KiCad 10.0.6 / native Python 3.11; same saved public fixture and default
Net tab before and after the layout change:

| Window size | Previous canvas | New canvas | Canvas area gain |
|---|---|---|---|
| 1280 × 800 | 724 × 661 | 1248 × 633 | 1.65× |
| 960 × 600 minimum | 404 × 461 | 928 × 433 | 2.16× |

Tests also open both drawers, adjust their widths, focus/restore them, resize
and scroll the expanded input panels, navigate tabs, and verify unchanged
result identity and saved PCB hash. The solved Results tab retains its folded
current-control header and at least 70% of client height at minimum size.

## Screenshot provenance

`help-viewport-first.png` is an opaque native client-area capture at 1280 × 800,
using the existing disposable `demo-power-board.kicad_pcb` test fixture. The
field is the analytical uniform 65 × 90 mm, 35 µm copper plate with full-height
edge electrodes at 5 V and assumed 2 A; its displayed drop is about 0.71149 mV.
The illustrated footprint/trace context is not that solved plate model. This is
a layout demonstration, not a measured-board result or a solver qualification.
No private design, username, machine path or credential is visible. No image
redaction or numerical alteration was required. Existing screenshots are kept.
