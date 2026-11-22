# Core embed API 1.0

KiCad WebView 1.0.0 establishes the documented core embed API as version `1.0`. Use the package entry points and shipped declarations; internal renderer globals, source-module internals and generated chunk filenames are not public contracts.

Within 1.x, removing or incompatibly changing a documented stable method, option, event or typed core export requires a new major version. Minor releases can add backward-compatible capabilities; patch releases can correct bugs. Rendering fidelity, diagnostics and bounded input validation can improve without preserving an earlier incorrect picture or accepting malformed files.

## Upgrading from 0.8.0

- `EMBED_API_VERSION` changes from `'1.0-beta'` to `'1.0'`. Update any exact checks of that metadata value. It is a contract identifier, not the npm package version.
- Existing `Viewer` / `KiCadViewer`, `ProjectViewer`, custom-element and iframe integrations retain their current method signatures. `setExplode` / `getExplode` remain compatibility aliases for `setExpand` / `getExpand`.
- Saved view-state and retained-result schema versions are unchanged. Restore operations still validate their source identities and hashes; a package upgrade does not authorize guessed cross-project matches.
- Balanced rendering caps its framebuffer at two million pixels, or one million on constrained devices. Photoreal Fast caps at one million to retain its memory ceiling while smoothing resolved color with SMAA. Low renders directly. Pixel limits are allocation policies, not FPS guarantees.
- In expanded Dim net focus, matching vias stay gold and unrelated vias become gray/translucent. Clear restores original materials and colors. Assembled-board plating and explicit Bright/Isolate styles remain available.

## Experimental and host-specific surfaces

Altium interoperability and the Slack, Confluence and Notion adapters retain their explicit experimental status. Their external host dependencies, permissions, authentication and client limitations are not certified by the core 1.0 version. In particular, the Forge source has not completed a live Confluence installation check. See [application integration limits](APP-INTEGRATIONS-BETA.md).

Native file compatibility and numerical visualization remain bounded by their documented formats. Viewing saved PI/SI/thermal results does not run a solver or qualify those results. Missing models, approximate geometry, unsupported files and incomplete stackups stay disclosed. A stable API does not imply KiCad pixel parity, every GPU/device, or maximum-budget 3D performance.

## Distribution and licensing

Classic scripts, ES modules, the lightweight entry point, iframes and self-contained HTML remain available. Node.js is a development/build requirement, not a requirement for website visitors. Pin a package version or host an exact reviewed bundle, keep its source revision and legal notices, and verify CDN bytes after publication.

MPL-2.0 permits free use, including commercially. Paid integration, customization, maintenance and support are optional. Hardware examples and third-party model assets retain separate terms and attribution.


## Upgrading from 1.0.0 to the 1.1.0 candidate

The core API identifier remains `1.0`. Layer preset/state types add `overview` and `preset`; manual edits, focus, restore and source replacement clear explicit preset state. Overview is offered only for 2D PCB.

Saved views add optional schematic `instancePath` and 3D `expand`. Old links without these fields retain their prior behavior. Forward the fourth restore callback argument when resolving files:

```js
await restoreViewState(viewers, state, {
  openFile: (index, path, signal, options) =>
    viewers[index].openFile(path, {signal, ...options})
});
```

`setExpand(amount)` remains animated. The additive `{animate:false}` option immediately restores a pose and cancels pending expansion frames. Read-only memory counters are available through `getRenderStats()`; they are renderer estimates/counters, not total process memory. Input acceptance ceilings are unchanged.

This candidate is not yet available from npm/CDNs. Continue pinning published 1.0.0 until 1.1.0 is published and verified.
