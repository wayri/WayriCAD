# Fanout live preview and performance - 23 October 2026

The planner now indexes nearby original board obstacles before running the same
conservative clearance checks. Original obstacle order and rejection order are
retained. Large query regions fall back to all obstacles; the index does not
remove narrow-phase checks. The shared canvas caches static pixels, clips
invisible geometry, translates cached pixels during dragging, and redraws the
exact view on release. Custom pad polygons remain intact.

## Fresh fixed-style planning

Windows, KiCad 10.0.6, native Python 3.11.5. Baseline:
`1251228408f164e2c3d3cd548558e006f27c6244`. Public Marble PCB SHA-256:
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
Three interleaved fresh-process trials per implementation, including index
construction but excluding loading, source fingerprinting and rendering:

| Scope | Baseline median | New median | Accepted / rejected |
|---|---:|---:|---:|
| U35, 361 pads, radial outward | 21.937 s | 0.294 s | 103 / 258 |
| U54, 100 pads, perimeter expansion | 6.771 s | 0.195 s | 0 / 100 |

Every full plan field, path coordinate and ordered rejection reason matched
exactly across all trials, as recorded by result SHA-256. The source file hash
and native board fingerprint also remained unchanged. U54's existing routed
geometry remains rejected; speed does not mean those cases became accepted.
Adaptive and connector searches use their existing split obstacle lists and
retain their original checks. These timing gains concern fixed styles only.

Reproduce with KiCad's Python from a checkout containing the baseline revision:

```text
python tools/benchmark_fanout_planning.py --board C:/Projects/Marble/Marble.kicad_pcb --baseline-ref 12512284 --output benchmark.json
```

The default settings reproduce U35. For U54 pass a JSON settings object with
scope Reference wildcard, ref U54, pattern Perimeter pitch expansion,
add_vias false, width 0.15 and clearance 0.1. Settings use millimetres.

## Native canvas

Same Marble U1 local context, native wx canvas at 1000 by 800 pixels. Context
contains 5,272 pads and 37,380 tracks; no source geometry was removed.
Each hover and drag row is a median of 30 paints. The full camera row uses ten
paints; extraction and release are single observations.

| Operation | Before | After |
|---|---:|---:|
| Hover paint | 330.87 ms | 1.80 ms |
| Drag paint | 324.84 ms | 2.04 ms |
| Full camera repaint | 326.31 ms | 99.40 ms |
| Exact release repaint | 328.07 ms | 101.62 ms |
| Board-context extraction | 0.411 s | 0.436 s |

Hover/drag reuse pixels rather than rerendering every board object. The final
release uses exact coordinates. These are paint-handler measurements, not
end-to-end operating-system frame-rate or PCB Editor IPC measurements.

The complete new native U35 preview method took 3.538 s initially and 2.862 s
on refresh in a separate two-call check, including planning, source checks,
context extraction/reuse and candidate construction, excluding painting and
initial board loading. Both calls retained 103 accepted / 258 rejected. Native
source fingerprint checks remain a major cost; the planner-only speedup must
not be presented as an equal end-to-end UI speedup.

## Workflow and validation

Live preview is enabled for selected parts/pads and narrowed reference scopes.
Input changes disable Apply immediately; a 300 ms debounce coalesces edits.
PCB selection is polled every 500 ms. Whole-board scopes and unrestricted
reference wildcards require explicit Refresh preview. The small preview uses
the same accepted plans as the main view, scoped to its component. Blocked
components remain inspectable. It never invents feasible routes or applies
copper automatically. Context reuse still requires a matching source hash.

- Native affected suite: **149 passed, 16 subtests passed**.
- Shared suite: **521 passed, 101 skipped, 227 subtests passed**.
- Native checks cover randomized rotated/offset pad broadphase coverage,
  group/pair/connector routing, local-rule export, CLI stale-plan guards,
  live main-loop preview, settings/geometry invalidation, read-only preview,
  Apply/Undo/Redo, cached hover/pan and native custom pad culling.
- A native QFP window changed styles through real combo events and the wx main
  loop; both styles produced 32 accepted escapes without adding board copper.
- The standalone harness stubs action registration because it has no running
  PCB Editor host singleton. Installed-editor/IPC interaction is not qualified
  by this source-window check. Native DRC remains required after adoption.

## Screenshot provenance

![Live fanout preview](../../fanout_generator_plugin/help-live-preview.png)

Actual native window on a disposable 32-pin QFP fixture: 0.5 mm input pitch,
0.8 mm outer pitch, 0.15 mm track width, 0.1 mm configured clearance, 0.5 mm via
and 0.2 mm drill. All 32 perimeter escapes were accepted. Dimensions illustrate
UI behaviour, not manufacturing recommendations. No private project files were
used or modified; no personal paths or identifiers appear, and no redaction
was needed. Existing help screenshots are retained.

[Raw trial data](FANOUT_LIVE_PERFORMANCE_2026-10-23.json). These source changes
postdate the published v3.6.26 binaries.
