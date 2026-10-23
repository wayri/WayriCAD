# Shared responsiveness and guarded routing

These are source changes after release 3.6.27. Measurements use Windows,
KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2. They do not qualify every
plugin, operating system or low-powered computer. No native backend rewrite
was needed for the measured improvements.

## Dense-board measurements

Public Marble contains 37,380 tracks, 5,272 pads, 3,664 vias and 1,374 named
nets in this fixture. Before/after values below are medians of three fresh
process pairs unless marked otherwise. Filesystem caches were not purged.
Timing a fresh process is not equivalent to a cold operating-system cache.

| Operation | Before | After | Scope |
|---|---:|---:|---|
| Populate eight full-net dropdowns | 890 ms | 225 ms | Same item ordering, selection and contents |
| Reapply dropdown widths 120 times | 2,140 ms | 2.86 ms | Reuses exact text metrics; does not rescan all strings |
| Quick PI first native window | 1.80 s | 1.34 s | Native source window |
| Quick PI cold geometry ready | 33.09 s | 20.26 s | Removes duplicate geometry extraction and batches inventory updates |
| Quick PI worst UI pause | 4.73 s | 1.16 s | Heartbeat measurement during that startup; still a material pause |
| QuickTherm inventory callback | 236 ms | 150 ms | 995 rows and 56 fields, not whole solver startup |
| SI setup imports | 925 ms | 236 ms | Numerical backend loads only when first needed |
| First exact viewport pick | 142 ms | 109 ms | Includes spatial-index construction |
| Subsequent exact viewport picks, mean | 133 ms | 0.211 ms | Same 46,200 selectable targets |
| First selected-net raster | 521 ms | 446 ms | Builds muted board context |
| Subsequent selected-net raster | 544 ms | 8.21 ms | Reuses context; redraws selected geometry |

The SI import change defers work: the first numerical operation pays about
574 ms for backend initialization instead of about 0.1 ms when it was already
imported. It does not accelerate the equations. Fixed microstrip results and
backend constants match the earlier implementation exactly.

Viewport geometry extraction hashes match before and after. Picking keeps the
original exact screen-distance test after conservative spatial filtering.
Changes to geometry or camera invalidate the appropriate caches. Hovering,
selection and repeated width changes avoid full-board work. Candidate previews
retain their separate geometry and do not reuse an incompatible context image.

The PI inventory, terminal defaults, mesh recommendation and extracted scene
match the earlier run. No PI, SI, RLC or thermal solver equations changed in
this work. Startup remains substantial on Marble; these measurements are not
evidence of real-time whole-board simulation.

## Routing previews and safety

Fanout and Via Stitching plan in a cancellable isolated process. The GUI shows
progress, accepted/rejected counts and before/proposed geometry. Automatic
native previews use a private copy of the saved board; save editor changes
first. An explicit live snapshot can include unsaved native changes, but its
serialization still runs on the owning UI thread. Serializing Marble took
about 2.8 seconds, so that option can pause the window. It is not used by a
continuous polling loop. IPC snapshot acquisition uses a separate originating
editor connection rather than sharing a GUI socket across threads.

Apply checks source geometry, selection, settings, companion files and routing
rules. The native identity now includes live manufacturing floors, keepout flags, pad shape/offset/drill,
custom copper, via spans/types, arc midpoints and board/footprint Edge.Cuts.
Mutation regressions cover changes that previously could leave the
identity unchanged. This more complete Marble check costs about 5.0 seconds
versus 3.0 seconds previously; it belongs at explicit review/apply boundaries,
not in hover or timer callbacks. Source-file CLI exports preserve project and
custom-rule companions and refuse existing output paths.

On Marble, the Fanout preview produced exactly the same 103 accepted and 258
rejected candidates, including an identical serialized candidate/rejection
digest. The old synchronous call blocked wx for 8.24–9.14 seconds. The new
saved-mode submission returned in 22–55 ms, with a worst 20 ms heartbeat gap
of 323–376 ms. Full completion took 13.72 seconds initially and 9.17/10.11
seconds on repeats. Isolation adds overhead; this is a responsiveness gain,
not a reduction in end-to-end planning time. Small component thumbnails show
the actual accepted geometry, while the main canvas retains the complete plan.

A separate screenshot harness returned after 98.7 seconds. Its original
end time measured native event-loop return rather than independently recording
UI completion. A subsequent instrumented run recorded worker activity through
10.5 seconds, UI completion at 13.06 seconds and immediate loop return after
queuing the exit callback. The final test harness owns a fresh native
`GUIEventLoop` for each preview wait instead of re-entering the application's
global loop; all 14 native UI checks passed with the final manufacturing-floor
safeguards. The original outlier did not separate these phases;
it is retained as a qualification limit, not silently averaged away or claimed
as a measured solver duration. The three timings above are observations, not
an upper latency guarantee.

Guard mode follows exact selected signal nets or captured straight-track IDs
on either or both sides. Guard net, pitch, offset and through-via dimensions
are explicit. Arcs are reported unsupported. Board holes, keepouts, filled
target copper and other-net obstacles remain constraints; budget exhaustion
and cancellation remain visible outcomes.

On a two-plane synthetic board, 22 proposed GND through-vias produced no new
native DRC findings after zone refill: five pre-existing silkscreen warnings
remained five. The actual native window completed in 2.72 seconds with a
109 ms maximum 40 ms heartbeat gap. A one-plane negative fixture instead
produced 22 dangling-via warnings. Passing geometric target-fill checks does
not prove connection to two conductive layers or useful RF shielding.

Tested Marble clock routes yielded zero legal guard candidates at the tested
offsets: lack of filled GND copper and local obstacles blocked them. The tool
does not relax board rules to manufacture a successful preview. A bounded
four-site grid comparison retained identical candidates/rejections and took
4.71 s before versus 0.55 s after spatial/native containment changes; this is
one pair, not a whole-board timing or statistical speed guarantee.

Marble's actual stitching window constructed in 0.50 seconds; the first
background preview plus full board context took 24.89 seconds. A 40 ms
heartbeat continued throughout, with a worst gap of 610 ms. Moving work away
from the window prevents the original long blocking plan, but does not make
this dense-board first preview instantaneous.

## Regression evidence

- Shared portable suite: 595 passed, 112 skipped, 464 subtests passed.
- Native viewport/dropdown/startup/label checks: 47 passed and seven subtests.
- Native guard UI, routing engine and CLI checks: 35 passed.
- Native Fanout live/connector UI checks: 14 passed, including actual
  component thumbnails, selection invalidation, Apply and Undo/Redo.
- Focused native Before/After, 680 × 480 action-button bounds and actual
  Apply/Undo workflow passed separately. Worker lifecycle/budget tests: five
  passed. Twenty-four disposable PCM archives passed package validation; both
  routing ZIP workers reproduced all 22 guard-via positions in isolation.
- Native geometry identity checks: nine passed, including saved/reloaded pad
  ordering, geometry-mutation rejection and unsaved manufacturing-floor changes.
- Portable Quick PI: 334 passed, 51 skipped, 383 subtests; QuickTherm: 254
  passed, 28 skipped, 196 subtests. Native dependencies account for skips.

These checks distinguish native source windows, portable calculations and
source-bound board-file operations. A complete running-editor IPC workflow
and low-powered hardware timing remain unverified.

## Reproduce a viewport measurement

Run from a source checkout with KiCad's bundled Python:

```text
python tools/benchmark_preview.py --board C:/Projects/Example/Marble.kicad_pcb --net +3.3P --net +3V3_USB --output preview-run.json
```

Use a fresh output filename and several separate processes per revision. The
JSON records versions, board hash, unchanged-input check, geometry digest,
import/load/extraction/raster timings and first/repeated pick timings. Reports
contain a board basename rather than the machine's full path. The harness
uses an offscreen native window, not a running editor IPC session or solver.
It does not measure low-powered hardware or purge operating-system caches.

Existing screenshots and plugin help remain available. See the
[Via Stitching workflow](../../via_stitching_plugin/ReadMe.md) and
[Fanout workflow](../../fanout_generator_plugin/ReadMe.md) for actual preview
captures, input controls and remaining geometry limitations.
