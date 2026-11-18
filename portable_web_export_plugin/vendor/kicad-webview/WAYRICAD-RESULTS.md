# WayriCAD saved-result integration

`WayriCADResultsViewer` displays retained Quick PI, Quick SI and QuickTherm results alongside the same saved PCB. It reads the existing WayriCAD portable JSON structures; it does not run a solver, execute HTML reports, fetch paths embedded in results, modify designs or execute firmware.

## Browser use without Node.js

```html
<div id="board" style="height:420px"></div>
<div id="results"></div>
<script src="https://wayri.github.io/assets/lib/kicad-webview/releases/0.4.0/kicad-webview.min.js"></script>
<script type="module">
  const board = new KiCadWebView.Viewer('#board', {theme:'dark'});
  await board.load('/designs/board.kicad_pcb');
  const results = new KiCadWebView.WayriCADResultsViewer('#results', {
    theme:'dark', boardViewer:board
  });
  await results.loadURL('/results/board.quick-pi.pocket-kivi.json');
  results.setBoardOverlay(true);
  await board.setView('3d');
  window.addEventListener('pagehide', () => {
    results.dispose();
    board.dispose();
  }, {once:true});
</script>
```

Supply your own explicitly hosted JSON and board URLs. Normal browser CORS applies; downloads omit credentials by default, with explicit `same-origin` available. Result imports are bounded to 64 MiB and reject duplicate keys, nonfinite input numbers, excessive depth/work and executable object properties. Keep smaller datasets or an explicit Load button for mobile readers. The main ES module exports the same API. The `/results` npm entry and `dist/wayricad-results.js` provide the result component independently; they include the matching field renderer.

In WayriCAD, use **Save results / Pocket KiVi** or the producer’s portable companion export. Keep the original solve-time saved PCB fingerprint. Hashing a newer PCB after an older run does not establish that the run used those bytes. [Producer export contract](https://github.com/wayri/WayriCAD/blob/0617fd201c0817d95648cec639744138aa59fe20/docs/POCKET_KIVI_EXPORT.md).

## Supported views

- **Quick PI:** saved triangular nodal potential, cell power and current-density magnitude. Missing nodes/cells remain transparent; values are not replaced with zero.
- **Quick SI:** saved route impedance, step responses and retained eye traces. Curves retain repeated time samples and break at missing values. SI curves are not converted into spatial PCB fields.
- **QuickTherm:** supported saved center grids, steady fields and layer-major transient frames. The frame slider uses saved times. Click a cell and choose Plot probe history, then Return to saved field. The color range remains fixed across the selected layer’s saved frames.
- **Independent 3D fields:** only supplied XYZ or explicit saved layer elevations are used. Scalar values interpolate before palette mapping, with the same palette/range as 2D. No result value becomes an invented height. A labelled vertex-color fallback may be used if the scalar shader fails; exact probe values remain retained. Unknown elevation uses the 2D view.
- **Complete numerical data:** a paged inert browser and full JSON download preserve original arrays, nulls, metadata and unsupported structures. Unsupported mechanical/volume or other plot shapes remain data; they do not acquire fabricated geometry.

The default chart selects up to four ordinary series or 32 eye traces. Series controls are paged, with 100,000 selected points in the bounded graph display. Limits and selection counts remain visible; the complete saved data is unchanged and downloadable. Independent 3D views retain source XYZ with +Z up and explicitly identify the producer’s Z basis; they are not automatically registered 3D PCB overlays.

Grid preview cell edges follow adjacent saved center spacing and are not clipped to PCB/copper boundaries or cutouts. A singleton or unordered grid axis is not enough to create an area surface. Use numerical data for unsupported grids. This is display geometry, not a reconstruction or validation of a solver mesh.

## Source registration and cross-selection

Pass a `KiCadViewer` as `boardViewer`, or call `results.attachBoard(board)`. A source badge distinguishes:

| State | Meaning |
| --- | --- |
| `matching` | The declared saved PCB SHA-256 equals the loaded source bytes; this does not authenticate or qualify the producer’s numerical claims. |
| `stale` | A single declared source hash differs from the loaded PCB. Board overlays and source actions are disabled. |
| `unverified` | Missing, ambiguous, unsaved or unsupported source evidence. Independent plots/data remain available; PCB registration is disabled. |

**Show on matching PCB** adds a display-only field overlay only when the result declares KiCad PCB XY millimetres and the source matches. Layer visibility and the PCB camera are respected. Switching the board between PCB and 3D retains the enabled field on the same source. The native 3D overlay maps saved front-depth or board-center Z; without saved Z only explicitly named F.Cu/B.Cu surfaces are placed. The selected field is shown through the substrate and components, with that presentation labelled. Hidden PCB layers hide their field. A source replacement immediately invalidates registration. SHA-256 registration needs HTTPS or localhost.

For supported SI exports, **Highlight saved net** and **Locate saved route** use the producer’s exact net name and segment UUIDs on the matching PCB. Selecting a linked PCB net/object reports its match in the result panel. No relationship is inferred from a graph label, a shortened hierarchical net name or an unrelated part reference. `highlightSource()` and `locateSource()` return false for missing, ambiguous or unregistered targets.

Complete `wayricad.project-result/v1` library records can expose supported plots and full data, but canonical project-library content identity is not verified by this adapter. They remain **unverified** for PCB registration. Export a supported portable companion with its original saved-source evidence for the registered route.

## Layers and linked probes

Choose **Saved result layer** to switch layers while retaining the field quantity where available. PCB layer visibility remains controlled by the native Layers panel. Click a result or PCB field to link its saved spatial probe marker; clicking a saved PCB part/segment samples its source anchor or segment midpoint. Native part/trace selection stays usable under the field. When the overlay is active the chosen result layer stays pinned; exact raycast probes retain their triangle, Z and value. A spatial marker does not assert electrical connectivity. SI net/route links use only explicit saved identities. Unknown values produce no marker.

`getResultLayers()` returns available names; `setLayer(name)` chooses one; `setBoardOverlay(boolean)` enables supported matching-source registration and returns the accepted state; `getBoardOverlayState()` returns placement/layer/basis/visibility feedback. `Viewer.getSelectionPosition()` returns a saved source anchor or segment midpoint with its layer, or null. `analysisprobe` emits registered native 3D probe data.

## API

| Method | Behavior |
| --- | --- |
| `load(jsonOrObject,{path?,signal?})` | Parse local JSON data without fetching. Returns `Promise<boolean>`; failed replacements preserve the prior result. |
| `loadURL(url,{path?,signal?,credentials?})` | Explicit bounded HTTP(S) JSON download. New loads supersede older work; caller cancellation rejects with `AbortError`. |
| `getResults()` | Frozen `{raw,report,sourceBindings,path,metadata}` or null. |
| `getSourceState()` / `getView()` | Copied state label and `2d`/`3d` mode. |
| `setPlot(index)` / `setFrame(index)` | Choose a retained plot/frame. Missing 3D coverage falls back to its 2D data rather than retaining an old field under a new time. |
| `setView('2d'|'3d')` | Open supported field geometry; unknown Z is rejected before 3D allocation. |
| `attachBoard(boardOrNull)` | Attach one explicitly supplied board viewer; no producer source path is downloaded. |
| `highlightSource()` / `locateSource()` | Act only on unique producer-declared names/IDs and matching saved bytes. |
| `setTheme('light'|'dark')` / `setOpacity(0..1)` | Local appearance controls; no source or result mutations. |
| `getRenderStats()` | Snapshot of the bounded raster preview and optional 3D rendering counters/range/fallback. |
| `clear()` / `dispose()` | Remove results or release listeners, pending loads, field buffers and scene resources. |

Events: `ready`, `plotchange`, `framechange`, `sourcechange`, `sourceselection`, `probe` and `error`. Pure helpers include `parseWayriCADResults`, `classifyWayriCADSource`, `getWayriCADSourceLinks`, `createWayriCADSurface`, `getWayriCADFrame`, `probeWayriCADPlot` and `getWayriCADPointHistory`.

## Evidence and example provenance

The public fixtures come from WayriCAD revision `0617fd201c0817d95648cec639744138aa59fe20`, with its retained README, native PCB inputs, project settings, original result JSON and upstream license. They are computed example producer runs under stated assumptions, not measured hardware or production designs. The eye plot is explicitly illustrative. No solver was rerun for this library integration. Original metadata spelling, including legacy encoded unit strings, remains unchanged; known plot labels follow the producer’s declared field conventions. No numeric unit conversion occurs.

Parser/spatial code is ported from owner-written KiCad Online sources, with original hashes and local missing-value/allocation fixes recorded in `SOURCE-PROVENANCE.json`. The full arrays remain available even when a plot/display limit applies. Use source identity, assumptions, units, boundaries, convergence and the producer’s own evidence before interpreting engineering conclusions. A successful view is not ERC/DRC, a protocol sign-off or engineering certification.

## Field palettes

The **Saved field palette** control selects `wayricad` (the existing default), `viridis`, `inferno` or `grayscale`. Viridis and Inferno are four-stop approximations, rather than full scientific lookup tables. The legend shows the active palette and numerical endpoints; missing samples remain transparent. Palette changes use the same stops in the independent 2D raster, standalone 3D scalar shader and fallback colors, and matching-source PCB/3D overlays.

```js
const results = new WayriCADResultsViewer('#results', {
  boardViewer: board,
  palette: 'viridis'
});
await results.load(savedResult);
results.setPalette('grayscale');
console.log(results.getPalette());
```

`setPalette(name)` changes presentation only. It retains saved values, source registration, fixed frame ranges, probes and the standalone 3D camera. Invalid names throw before changing the current palette. `palettechange` emits `{palette}`; `getRenderStats()` includes the selected palette. Use matching viewer and 3D runtime versions. Registered fields and probes remain suspended during exploded-board inspection and restored when assembled; changing a palette does not override this policy.
