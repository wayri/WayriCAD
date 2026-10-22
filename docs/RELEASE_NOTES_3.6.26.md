# WayriCAD 3.6.26

This release packages the Quick PI responsiveness and net-selection fixes,
plus Trace Refiner 0.3.1. Refresh WayriCAD in KiCad's Plugin and Content Manager,
install the updates, and restart PCB Editor. Individual PCM ZIPs and the Python
wheel are also available on the release page.

| Change | What to expect |
|---|---|
| Repeated Quick PI runs | Identical successful saved-board requests can reuse bounded, source/settings-keyed results. On Marble, an uncached request took 13.4 s and its cached repeat took 0.75 s. Changed models or files still require a fresh solve. |
| Responsive board display | Selected-net native display extraction moved into the worker and skips unrelated copper before tessellation. Marble extraction measured about 2.7 s instead of 10.3 s for the full scene; surrounding copper loads on request. Unchanged plot artists and display paths are reused. |
| Net search | Case-insensitive text, `*`/`?` wildcards and `~text` fuzzy suggestions. Bus brackets stay literal. Filtering preserves selected nets and checked items. The bounded fuzzy shortlist measured about 30 ms on repeated queries over 10,000 synthetic names. |
| Focused maps and PCB selection | Only simulated nets is enabled by default. Exact net identities prevent similarly named nets or unrelated component pads from being selected. Result maps and reports support an all-copper-layer projection; fields are not summed or averaged. |
| Trace Refiner | Fixes bindings without `PCB_TRACK.SetUuid`, verifies replacement identities, and retains native DRC/connectivity/Undo guards. Amber original and teal proposed routing can be reviewed as Overlay, Before, After or Side by side. A generic wx progress dialog avoids the native validation-dialog closing crash found in testing. |

Fresh complete Quick PI solves were not materially faster in the final
unprofiled comparison, although its meshing stage improved by 11.6%. Result
reuse is not a new FEM solve. Fuzzy search is a bounded suggestion list, not an
exhaustive best-match guarantee. Combined-layer projections can visually
occlude a lower layer; choose an individual layer for unambiguous inspection.

The 17 IPC packages advance to 3.6.26 because they carry the updated shared
runtime. Trace Refiner advances to 0.3.1. Five other native packages keep their
versions and unchanged package bytes. There are 23 independent plugin ZIPs.

Validation and measured limits:

- [Quick-tool display and interaction measurements](audits/QUICK_TOOLS_PERFORMANCE.md)
- [Quick PI backend equivalence and cold/warm timings](audits/QUICK_PI_BACKEND_PERFORMANCE_2026-10-22.md)
- [Search performance and shortlist limits](audits/NET_SELECTION_PERFORMANCE.md)
- [Release packaging checks](audits/RELEASE_3.6.26.md)

Windows native checks used KiCad 10.0.6 and Python 3.11.5. Native evidence is
separate from portable CI and does not establish live-editor IPC qualification
on every platform. No user project was included in the packages or modified.
