# Stable panels and contextual previews

The inspector is an overlay. Opening, closing or resizing it does not resize the
canvas, refit the board or change the camera. Its Properties section retains its
scroll position during selection updates; keyboard focus returns to the same
action when that action still exists. Loading a new source resets that scroll.
Parts and Nets search inputs remain mounted during selection updates.

```js
import {Viewer, ViewerInset} from './kivi-viewer.js';

const pcb = new Viewer('#pcb', {theme:'dark', inspectOnSelect:false});
await pcb.load('/boards/controller.kicad_pcb');
pcb.setInspectorWidth(360); // 240–480 CSS pixels; local to this instance
pcb.setInspectorOpen(true);
console.log(pcb.getPanelState()); // {open, preferredWidth, width}
```

Drag the inspector's left edge, or focus its separator and use Left/Right,
Shift+Left/Right, Home or End. Narrow hosts clamp the displayed width without
overwriting the preference; small embeds use a bottom drawer. Inspector tabs and
view switches use the same selected-state treatment in light and dark themes.
No preference is written to a website's storage.

## Contextual previews

Select a saved part, pad or net and choose **Open contextual preview** in its
Properties, or create the preview from a script. A floating preview follows
selection without moving the main camera. Opening another floating preview
replaces the previous floating preview.

```js
const preview = await pcb.openInset(); // loaded PCB, initially a 2D preview
// Fit selection and Close are also available as buttons.
preview?.focus();
preview?.dispose();
```

For a schematic-to-PCB or PCB-to-schematic inset, explicitly supply another
already-loaded viewer. The saved symbol/footprint UUID relationship must be
unambiguous. Reference names alone never establish a link.

```js
const schematic = new Viewer('#schematic', {inspectOnSelect:false});
await schematic.load('/boards/controller.kicad_sch');
await schematic.openInset({sourceViewer:pcb, view:'3d'});

// An independent host-managed panel uses the same implementation.
const inset = new ViewerInset(document.querySelector('#context'), {
  parent:schematic, sourceViewer:pcb, view:'pcb'
});
await inset.ready;
```

Selections link in both directions using existing source-bound matching. Received
selections do not force Properties open. Same-drawing net links require identical
source bytes and path; sheet-local net names are not guessed across documents.
Each parent owns at most two insets. They close and release listeners/renderers
when their parent or source viewer is disposed or loads different source bytes
or a different path. Each preview has its own camera; dragging it does not pan
the parent.

Insets never discover repository files, upload sources or fetch a project just
to find a match. They render the explicitly supplied viewer's loaded source.
Optional 3D previews retain the normal runtime/model-loading rules and consume
an additional bounded renderer, so use the default 2D preview on constrained
devices. This is a read-only library feature, with no comments or design editing.

These examples use ordinary browser modules and require no Node.js on the
embedding website. Use the locally built bundle containing these APIs; a
previously published package does not gain new source features automatically.

## Design reference

Interaction patterns were reviewed against [KiCAD Prism](https://github.com/krishna-swaroop/KiCAD-Prism), including its stable overlay rails and contextual cross-probing. The implementation uses WebView's own renderers, source identity checks and host controls. These are unreleased local-development additions. Use the matching rebuilt distribution. Source regressions and local Chromium/GPU smoke checks passed; installed-extension and physical-device acceptance remain separate.

The viewer retains its own ribbon, popup styling, theme tokens and explicit buttons. Workflow references do not define its visual design. Context previews reuse the normal viewer controls; major locate, cross-selection and focus actions are automated using saved identities.


## Safe preview replacement

`openInset()` keeps the accepted floating preview visible while a replacement
prepares. Invalid options or failed rendering leave that accepted preview and
the main camera intact. Only the newest floating request can be accepted;
superseded requests resolve to `null`. Closing the accepted preview also cancels
a pending replacement so it cannot reopen later.

Preparation counts toward the two-inset limit. If both slots are occupied,
close an inset before requesting a replacement. A rejected request leaves both
accepted previews intact; the viewer never creates a third renderer to stage it.

With no explicit `selection`, a preview reads the parent's current saved
selection after loading. Its initial selection is applied locally; opening it
cannot replay an earlier click or clear the parent's selection. An explicit
`selection` (including `null`) initializes only the preview. Subsequent clicks
continue to cross-select through the normal saved-identity checks.
