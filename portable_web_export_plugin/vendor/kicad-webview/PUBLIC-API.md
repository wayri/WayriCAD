# Embed API 1.0-beta

Use the documented package entry point, not internal renderer globals. Public declarations ship in `types/index.d.ts`. `EMBED_API_VERSION` identifies this beta contract. The legacy full ESM entry and classic `KiCadWebView` global expose the same compact viewer; `ProjectViewer` adds read-only project navigation. Browser visitors need no Node server.

```js
const viewer = new KiCadWebView.Viewer('#board', {theme:'dark'});
viewer.addEventListener('ready', ({detail}) => console.log(detail.path, detail.view));
viewer.addEventListener('select', ({detail}) => console.log(detail.item));
viewer.addEventListener('viewchange', ({detail}) => console.log(detail.view));
viewer.addEventListener('error', ({detail}) => console.error(detail.message));
await viewer.load('/design/project.json');
const net = viewer.getNets().find(n => n.name === 'VCC');
if (net) viewer.selectNet(net.id, {locate:true});
// Unmount: viewer.dispose();
```

Loading: `load`/`loadProject` accept a hosted drawing, manifest or supported repository URL. `loadFiles` accepts local browser files or path/source entries; `loadArchive` accepts bounded ZIP bytes. `openFile` is confined to the loaded project. These return a Promise of true on completion, false when superseded/disposed, or reject for a current load error. The `ready` event occurs for each successful rendered view, not just the first network fetch. Local files/results stay in-browser.

Selection: `getParts`/`selectPart` use saved identities; `getNets`/`selectNet` prefer per-drawing net IDs and allow a name only when unique. PCB pads/traces/vias/zones highlight their complete saved net by default. Uncheck “Highlight entire net” for object-only highlighting. Hidden layers stay hidden. `clearSelection` clears highlight/selection; `setInspectorOpen` controls the inspector. Schematic connectivity comes from bounded per-file source wires/labels/terminals and is not KiCad's netlist; implicit hidden power pins, buses and repeated-sheet instance resolution are limited. `getSheets` returns saved child-sheet links and resolves only project-listed targets.

View: `setView` accepts schematic for schematic files, PCB/3D for boards, or manufacturing for CAM. `fit`, `getLayers`/`setLayers` and `setTheme` reuse the existing viewer controls. `getCamera` returns a copied 2D camera snapshot for PCB/schematic or null otherwise. `setCamera` accepts that complete snapshot; center is saved mm, zoom is CSS pixels/mm and flipped is boolean. It does not control the 3D camera or manufacturing camera in this beta. Camera events describe changes, not every paint. `setMeasuring` currently controls the manufacturing ruler; 3D surface measurement remains a viewer control rather than a public programmable API.

Events are native CustomEvents with typed `detail`: `ready` (path/view/revision/warnings), `select` (item/path/view/multi), `error` (Error), `viewchange` (view/path), `camerachange` (copied camera/view/path), `analysis` (fields/provenance), and `measure` (CAM measurement). The custom element forwards these under `kicad:` names. Event listeners should be attached before loading. Analysis APIs and result provenance are documented in ANALYSIS.md. ProjectViewer events and saved-UUID linking limits are documented in ADVANCED-VIEWER.md.

Lifecycle: mount one viewer per container; independent containers have independent cameras, layers and source state. Dispose before reusing a container. Disposal aborts pending work, unregisters listeners and releases renderer resources. In React/Vue/etc., create in mount/effect and call dispose in cleanup; do not create a new instance during every render. A minimal framework-independent lifecycle is `const v = new Viewer(element); await v.load(url); return () => v.dispose()`.

Use static self-hosted assets with an explicit mount height. Cross-origin source downloads require CORS; library credentials are omit by default, with explicit same-origin only. This API is not a cross-origin iframe command bridge. Do not send private/signed URLs through public embed links. Comments, authentication services, native CAD editing, native ERC/DRC/solver execution and extension review workflows are outside the library contract.

## 3D appearance and statistics

The `appearance` constructor option defaults to `realistic`; `setAppearance('realistic' | 'layers' | 'translucent')` changes the loaded 3D view and returns the active mode. `getAppearance()` returns that mode or null outside 3D. `getRenderStats()` returns a copied snapshot or null outside 3D, including appearance, draw calls, render count, loaded model and component counts, and model update counts and CPU time.

Display → Appearance → Translucent makes the board and models translucent, shows copper in actual layer colors, and keeps fills faint. Saved XY positions are exact. Where stackup information is absent, internal copper elevations are illustrative and a diagnostic identifies this; transparent raster sorting can produce visual ordering artifacts. Layers remain independently hideable, and selecting then clearing a selection restores translucency. Model refreshes are batched progressively, and internal copper is constructed lazily.

## 3D net selection and presentations

`selectNet(idOrUniqueName)` also works in 3D: saved copper is accented while unrelated surroundings are greyed. Selection survives layout/3D switches for the same drawing; loading another source clears it. `setCamera3D(preset)` accepts top, bottom, front, back, left, right and isometric while in 3D. It uses named board framing; `getCamera`/`setCamera` remain 2D-only. See [ViewerCarousel](CAROUSEL.md) for live project and 3D board presentations.

Loading operations (load, loadFiles, loadArchive, loadSource and loaded-file navigation) accept AbortSignal. A pre-aborted source call rejects before parsing. Cancellation while the optional 3D runtime loads preserves the current source, path, design and renderer; the shared import may finish, but cannot mount a cancelled operation. Each current failed load or direct setView operation rejects and emits one error event. Superseded/disposed operations return false without a misleading error. Failed replacements preserve selection/event forwarding from the still-mounted renderer; genuinely replaced renderers cannot emit current selection events.

## Linked views and source-bound URLs

linkViewers([schematic,board,assembly]) links explicitly supplied viewers (2–8). Exact saved parts cross-probe between schematic and PCB; identical source/path drawings also cross-select saved pads, tracks, vias, zones and nets. Clear selection propagates. Cameras remain independent; no reference-only or cross-sheet net-name guesses are made. Dispose the link group separately from its viewers. See LINKED-VIEWS.md.

getSelection() returns a copied saved-identity summary; selectObject(uuid,{locate:false,pinNumber}) restores saved objects/terminals. getCamera3D() returns copied board-centred millimetre position/target/up vectors. setCamera3D accepts that snapshot or a named preset; getCamera/setCamera remain 2D-only. setView(view,{signal}) supports cancellation while optional 3D loads.

captureViewState(viewers,settings), createViewLink(baseURL,state), parseViewLink(url) and restoreViewState(viewers,state,options) support opt-in URLs. They contain paths, source hashes, cameras, layers and selection identities rather than design bytes. Hosts load their project first; restoration checks exact SHA-256 before applying camera/selection state. The advanced viewer provides getViewState(), createViewLink() and restoreViewState(), plus a Create view link control. The advanced example opts into fragment restoration. See VIEW-LINKS.md for bounds, cancellation and partial-load behavior.

## Scripted 3D demo controls

DemoController(viewer) adds explicit caller-scripted LED/display/button/knob overlays to the current native 3D scene. viewer.pickDemoFace({signal}) lets the user choose an actual planar component face; drawDisplay, writeImage and setPixels feed bounded graphics onto it. bindKey scopes input to the focused viewer, and input/error/suspend events expose script behavior. Scene replacement suspends controls rather than reattaching them to guessed geometry. The saved design is unchanged; this is presentation, not an electrical simulation. See [interactive demo API](INTERACTIVE-DEMO.md).

## Embedded camera navigation

3D views include named-view, orbit/tilt, roll and zoom buttons, plus focus-scoped shortcuts. viewer.rotate3D(direction, degrees=15) rotates the current camera while preserving its target/distance. See [view controls and keys](VIEW-NAVIGATION.md).

## Independent project hierarchy

buildProjectHierarchy(files,{root,entry}) builds source-derived root/subsheet instance data. loadProjectHierarchy loads listed sources; ProjectTree mounts an expandable diagram, emits sheet selection and exports script-free SVG through toSVG(). Available in full/lite entries and the independent /hierarchy subpath. See [project tree API](PROJECT-TREE.md).

## Highlight and layer controls

See [inspection controls](INSPECTION-CONTROLS.md) for setHighlightStyle/getHighlightStyle, getLayerState, layer presets, 2D focus/fit/restore, 3D copper visibility and per-instance behavior.

See [mobile website performance](MOBILE-PERFORMANCE.md) for rendering suspension, source reuse, statistics and no-Node embedding guidance.

## WayriCAD saved results

`WayriCADResultsViewer` provides inert saved PI/SI/thermal fields, curves, frames and data, optional exact-hash-registered PCB overlays and producer-identity source links. `parseWayriCADResults`, `classifyWayriCADSource`, `getWayriCADSourceLinks`, `createWayriCADSurface`, `getWayriCADFrame`, `probeWayriCADPlot` and `getWayriCADPointHistory` are pure model/query helpers. See [the result API, examples and limits](WAYRICAD-RESULTS.md). The `/results` entry supplies this component separately.

Version 0.4.0 adds registered native 3D PCB fields, `WayriCADResultsViewer.getResultLayers()`, `setLayer(name)`, `setBoardOverlay(boolean)` and `getBoardOverlayState()`. `Viewer.getSelectionPosition()` exposes a saved anchor or segment midpoint. Registered `analysisprobe` events retain the exact saved field hit. See [the result guide](WAYRICAD-RESULTS.md).

## Native BOM and board analytics (0.5.0)

`BOMViewer`, `buildBOM`, `analyzeBoard` and `bomToCSV` are exported by the full SDK and dedicated `./bom` entry. See [BOM API, examples and limits](BOM-ANALYTICS.md).
