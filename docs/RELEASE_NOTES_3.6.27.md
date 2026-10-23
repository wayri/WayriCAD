# WayriCAD 3.6.27

This release brings faster fresh Quick PI solves, a more responsive board view,
and faster Fanout planning with live component style previews. Refresh WayriCAD
in KiCad Plugin and Content Manager, install updates, then restart PCB Editor.
All 23 independent PCM ZIPs, a Python wheel and a source archive are attached.

| Change | What to expect |
|---|---|
| Fresh Quick PI solves | A multi-net batch owns one native PCB; geometry, mesh bookkeeping and matrix assembly avoid repeated Python work. Two-rail Marble cold median: 43.24 s to 31.71 s, with matching electrical results. |
| Native board appearance | Saved visible silkscreen keeps its physical size, rotation and position. Invented centroid labels, repeated source/load captions and default fab/courtyard clutter are removed from the board view. Scientific report captions remain. |
| Responsive navigation | Full Marble viewport redraw: 763 ms to 58 ms. Dragging uses cached pixels with exact redraw on release; indexed exact-cell probes avoid full redraws for unchanged values. 3D capture loss resets the gesture correctly. |
| Fanout live previews | Select parts/pins and choose a style. Live preview updates after a short pause; a small component preview shows the actual accepted routes. Apply remains separate. Broad scopes use explicit Refresh preview. |
| Faster fixed fanout planning | Nearby-obstacle indexing retains existing clearance checks and ordered rejections. Marble U35: 21.94 s to 0.29 s; U54: 6.77 s to 0.19 s, with exact output equivalence. |
| Faster shared routing canvas | Marble hover painting: 331 ms to 1.8 ms. Cached pan, exact release rendering and offscreen culling retain native pad polygons. Help, screenshots and workflow guidance are updated. |

Timing scopes differ: planner-only gains exclude loading, source checks and
rendering. The complete new U35 preview took 3.54 s initially and 2.86 s on
refresh. Initial full Quick PI scene extraction remains about 9.6 s. No mesh
target, material value, solver tolerance or routing clearance was relaxed.
Blocked routes remain rejected; a fanout seed is not a completed or DRC-qualified
route. Native DRC and engineering review remain necessary.

The 17 IPC packages advance to 3.6.27 to deliver their updated shared runtime.
The six unchanged native packages retain their existing versions and bytes.

Validation evidence and limits:

- [Quick PI fresh-solve comparison](audits/QUICK_PI_COLD_PERFORMANCE_2026-10-22.md)
- [Board rendering, probes and native-window checks](audits/QUICK_PI_VIEWPORT_PERFORMANCE_2026-10-23.md)
- [Fanout exact-equivalence and UI measurements](audits/FANOUT_LIVE_PERFORMANCE_2026-10-23.md)
- [Release packaging checks](audits/RELEASE_3.6.27.md)

Native evidence uses Windows, KiCad 10.0.6 and Python 3.11.5. Portable CI and
standalone native windows do not establish live-editor IPC compatibility on
every OS. No private board or validation cache is included in the release.
