# Board-first workspace

QuickTherm starts on **Board + results** with both sidebars closed. The startup
canvas explains Components → Setup → Run; it does not invent board geometry or
thermal results before a simulation is available. The Component inputs tab is
still a full-size table. The persistent header provides Components, Run and
Files. Files invokes the existing setup/result save and load handlers, report
and Blender exports, and the dissipation Sankey.

**Setup** opens the independently scrolling input form. **Details** opens the
results, probes and 3D inspection notebook. Their divider widths are retained
when closed. **Focus view** hides the open panels and restores them when toggled
off. At narrow widths, opening one sidebar closes the other to preserve useful
board space. Time playback and its time selector only appear when computed
transient frames exist; steady-state views keep those controls out of the way.
The plot toolbar provides the single Fit action. Shrinking a window with both open closes Details; it does not
change inputs, results or component selection.

## Native layout evidence

Windows, KiCad 10.0.6, native wx with the existing scientific runtime. The same
public `docs/examples/pocket-kivi/quick-therm.pocket-kivi.json` result was loaded
into the previous committed and updated UI, without running a new solve. The
saved result uses illustrative inputs, not measured hardware data. Window sizes
include native decorations; canvas dimensions are actual native widget sizes.

| Window | Previous canvas | Board-first canvas |
|---|---:|---:|
| 1280 × 800 | 560 × 447 | 1244 × 560 |
| 940 × 680 (minimum) | 240 × 256 | 904 × 440 |

`help-viewport-first.png` is a 1264 × 761 RGB native client-area capture at the
1280 × 800 window size. Its visible filename is the public thermal demo name.
No private paths, credentials or project identifiers are present; no redaction
was needed. The figure contains original saved samples and unknown cutout
values. This screenshot proves the native display/layout, not solver accuracy
or editor-linked cross-selection.

Native tests cover default viewport proportions, minimum-size file/run access,
reversible sidebars and widths, Focus restoration, narrow-window behavior,
field-mapping navigation and expanded-form horizontal/vertical scrolling.
