# WayriCAD 3.6.30

Fanout now produces working BGA and partly routed connector escapes on Marble
copies, with native zone refill and DRC checks.

| Fix | Result |
|---|---|
| Actual copper shapes | Circular pads, diagonal tracks, arcs and per-layer padstacks no longer block their whole bounding rectangles. |
| Copper pours and keepouts | Pours refill around new routes; rule areas retain their actual boundaries, holes and layer restrictions. Non-plated holes block every copper layer. |
| Partly routed pins | Adaptive can extend a short launch wholly inside a pad while retaining existing copper. |
| BGA search | Adaptive includes package-pitch centers between user-selected grid points. |
| Connector speed | Reuse spatial indices and try legal direct exits before grid search. Netclass groups share immutable board indices. |

On the deliberately unrouted U35 copy, the same Fixed BGA scope improved from
zero to **290 accepted escapes**. Comparable worker time was 10.72 → 9.14 s;
the planner alone took 1.80 s. Native refill/DRC introduced zero new errors and
preserved all existing copper, pads and connected pad groups. Both deliberately
disconnected active J9 signals and eight selected P1 pins also passed native
checks with no new errors.

These are escape routes, not complete autorouting: dangling track/via warnings
remain at unfinished ends. Seventy fixed BGA locations still fail actual copper
clearance and one retains connected copper. Existing Marble findings remain.
See [measured scopes and validation](audits/FANOUT_DENSE_BOARD_FIXES_2026-10-23.md).

After Apply or opening an exported/CLI candidate, **refill zones (B), then run
DRC**. Refresh WayriCAD in KiCad Plugin and Content Manager, install the updates
and restart PCB Editor. All 24 independent packages include the updated shared
runtime. IPC packages use 3.6.30; native package patch versions are Trace Refiner
0.3.3, Fusion 0.9.13, Variant Manager 0.6.6, Component Arranger 0.1.5,
Layer Counter 0.1.5 and Silkscreen Placer 0.3.5.
