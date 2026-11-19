# Highlight and layer inspection


## Unreleased source additions

These changes are prepared in source and are not part of the published 1.0.0 package yet.

In the **2D PCB** Layers menu, **Overview** shows only saved `F.Cu`, `B.Cu`, `F.SilkS`, `B.SilkS` and `Edge.Cuts` layers. It is a distinct explicit preset; it stays selected when the board has only those layers and All happens to show the same set. Inner copper, fabrication and courtyard layers are excluded. Manual layer edits, focus/clear focus, Restore and document replacement clear the chosen-preset indicator. Restore retains the original visibility snapshot across consecutive presets and focus operations. Overview does not change the camera and is not offered for 3D or manufacturing views.

```js
viewer.setLayerPreset('overview'); // unreleased source API; requires 2D PCB
console.log(viewer.getLayerState().preset); // 'overview'
viewer.setLayers(['F.Cu', 'Edge.Cuts']); // preset becomes null
viewer.restoreLayerView();
```

PCB Dim net context uses 0.045 opacity, neutral gray including unrelated vias. Selected saved copper is drawn after that context, with physical drill cutouts last. Matching vias retain gold; hidden layers and layer/net isolation remain respected. Schematic context stays at 0.38; Bright and cleared source drawing order remain unchanged. No blurred glow is added. Rendering honors saved primitive opacity in addition to context opacity.


The project sheet browser now passes saved root/sheet UUID occurrence paths when opening repeated sheets. Independent `ProjectTree` selections expose `instancePath`; hosts can pass it to `project.openFile(node.path, {instancePath: node.instancePath})`. This preserves loaded schematic text context for repeated occurrences; it does not infer a hierarchical netlist or fetch unlisted ancestors. Load the listed schematic sources together for ancestor-dependent text resolution.

Each embed has independent settings. Source/layer colors are the default for highlights; Accent color remains optional. Plated vias stay gold in 2D and 3D, including selected nets. Clicking saved copper highlights its complete source net by default; the inspector retains the clicked object properties and explicitly reports the full-net scope. Disable “Highlight entire net” for individual-object inspection. In **Highlight settings**, choose Dim context, Bright only, or Isolate selection, and Accent color or Source colors. The style applies to saved parts, pads and nets in PCB, schematic and 3D views. Isolate removes unrelated selectable content while retaining board context. Clearing selection restores source materials and geometry; hidden layers remain hidden. The properties popup remains optional through inspectOnSelect.

Open **Layers** for searchable saved layer names, colors and primitive counts. All, None, Front, Back and Copper presets change visibility. In 2D PCB view, Focus dims or isolates one layer, Fit focused layer frames its saved geometry, Clear layer focus leaves visibility in place, and Restore view restores the visibility saved before presets/focus. [ and ] cycle layers; Shift+F fits the focused layer when the drawing has keyboard focus. Text fields keep their normal keyboard behavior.

In 3D, the same Layers panel controls physical saved copper layers. Internal layer preferences apply when Translucent appearance is active; Reveal internal copper switches to that appearance. Layer focus/fit is a 2D PCB operation. Manufacturing supports layer visibility and presets; a CAM file does not supply PCB part/net metadata.

~~~js
const viewer = new Viewer('#board', {highlightStyle:'dim', highlightColor:'accent', inspectOnSelect:false});
await viewer.load('/designs/project.zip', {view:'pcb'});
viewer.setHighlightStyle('isolate', {color:'source'});
viewer.focusLayer('F.Cu', {mode:'isolate', fit:true});
viewer.restoreLayerView();
await viewer.setView('3d');
viewer.setAppearance('translucent');
viewer.setLayers(['F.Cu', 'B.Cu']); // use names from getLayerState().layers
~~~

getHighlightStyle() and getLayerState() return copied settings. Invalid styles/layers are rejected before display state changes. Layer state is renderer-local; reopening a drawing creates a fresh layer view, while highlight settings persist for the viewer instance. Events highlightstylechange and layerschange report host-API updates. No comments or write permissions are added.

## KiCad Online parity

This update exposes the upstream 2D inspection modes and layer-focus mechanisms through the standalone library controls and API. It preserves the library's precise picking priority, translucent mode, linked selections, project navigation and scripted model interactions. The newer schematic parser displays multi-unit reference letters and combines saved symbol/field rotation without changing field anchors or selection identities. Tests use the retained KiCad 10.0.6 native-orientation cases; a fresh native export was not run for this port.

Read-only upstream snapshot (working source, not a claim of a released extension version):

- extension/schematic-renderer.js SHA-256 90142cb46172d9928281620046e7bf913ed4dca194429b9f8f64be08504c8a17
- extension/pcb-renderer.js SHA-256 3d70d4ba089f23b22503d7faa0f9d42844c15a5cff4be076355cb60e99dd0337
- extension/owned-canvas.js SHA-256 a225ca7e8cd7cb2b5520d12681d4d86dca7044cb82989ca51ce675dab869194e

## Embed and offline entry points

New local integrations also accept initial highlightStyle, highlightColor and appearance in buildEmbedURL() options and hosted embed query parameters. The custom element supports highlight-style, highlight-color and appearance at initial connection. Invalid values use the same validation as the Viewer constructor; no arbitrary styles or scripts are accepted.

createStandaloneHTML() is available from the main library export as well as its standalone module. It accepts those initial options alongside the classic viewer script, license/source notices and bundled files. Its exported HTML keeps connect-src 'none'; the new controls do not require a network connection.

Advanced project viewers provide a Layers navigator tab for the active pane, reusing each pane's layer API. Layer visibility remains local to that pane even when saved part/net selection is linked.


[Stable panels and contextual inset previews](PANELS-AND-INSETS.md) document inspector sizing, selection-linked previews and source/lifetime limits.
