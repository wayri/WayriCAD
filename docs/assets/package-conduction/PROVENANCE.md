# Native conduction snapshots

Captured on 2026-10-10 on Windows using KiCad 10.0.6 Python 3.11.5 and wxPython 4.2.2.
These are development UI captures, separate from the published 3.6.13 GUI set.

`tools/check_package_conduction.py` generates a 30 × 15 mm rectangular board
with one 1 mm-wide VCC track, J1 and U1. Both contacts contain a rectangular lead
and truncated spherical solder segment with explicitly illustrative material
properties. The electrical study uses 3.3 V and 2 A. Component heat sources are
0.1 W and 0.2 W; thermal playback includes separately imported copper and joint
Joule heat. The thermal capture shows the 1 s final frame.

| File | Capture |
| --- | --- |
| `quick-pi.png` | Native result window, including contact loss summary |
| `quick-therm.png` | Native final transient frame with compact sidebar controls |
| `rejected-material.png` | Thermal contact editor rejecting nonfinite conductivity |

The captures contain only generated public fixture geometry. Headers, status
lines, controls and PNG metadata were checked for personal usernames, private
paths and network addresses. No redaction or image editing was needed. Captures
use the application client area and omit the operating-system window frame.
Numerical values and rejected input are preserved. These images establish the
displayed UI state, not physical material or model qualification.
