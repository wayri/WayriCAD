# Actual Offline Browser Captures

These images were supplied by the coordinating browser-validation task and
visually inspected before copying, without alteration. They show an actual
exported HTML page in desktop Chrome, not the native KiCad window. The existing
workflow/preview illustrations remain separate and are not replaced.

## Input and Render Scope

- Public KiCad 10 installation demo: `share/kicad/demos/pic_programmer`.
- Viewer: the official KiCad WebView 0.6.0 classic runtime, pinned by
  [the integration inventory](vendor/kicad-webview/PINNED-DISTRIBUTION.json).
- Export document ID: `7b75b3a7340112bac9a58b6f`.
- Revision: `6aaac3d951d4deb3c0395ad9`.
- Generated UTC: `2026-11-12T19:42:36+00:00`.
- Export HTML SHA-256: `ca9cd0ac0890c2fe1b94989f5da45660f6a1343fe19e9fe668d56c60c90fc500`.
- Bundled model assets: **0**. Unresolved models use labelled stand-ins; their
  body shapes are not qualified component geometry.
- No private design or native application window was captured. Inspection found
  no personal username, local directory or private network address in the images.
  No redaction or other image editing was performed.

| Saved input | SHA-256 (also equal to its bundled hash in this capture) |
|---|---|
| `pic_programmer.kicad_pcb` | `aba03b4359e8bf162fe00b27b0d3394f2141acfbd3d43d9cf8e05bf0845d9bd5` |
| `pic_programmer.kicad_sch` | `e5464cb02c5a045d8faea8568ad21a68f89e803c07d0901a41114d30bce60618` |
| `pic_sockets.kicad_sch` | `60c291720cde6d5626fa95fc16aa545b5557388245b6f2568581ebcbfbb48543` |

## Images

| Image | Actual state | SHA-256 |
|---|---|---|
| [help-offline-pcb.png](help-offline-pcb.png) | 1280 x 800; saved GND net selected, property inspector open | `67e209b8b2ba4fff687f635055f469c78e4e4a36ba0fc490f3f7017163931349` |
| [help-offline-3d.png](help-offline-3d.png) | 1280 x 800; public 3D view, explode 35; inspector open | `8ff7857a5b536e447dd08456a372375456d7edf3b11217658790aa9ba833d44f` |
| [help-offline-mobile.png](help-offline-mobile.png) | 390 x 844; controls and net inspector; no page-width overflow | `ecb4da57529e140130ca07946f106d1c09619442b72a28f923a4a1d3a52f027c` |

The coordinating Playwright run reported 63 parts, 111 nets, successful GND
selection/inspection, 3D explode 35, zero offline HTTP requests and zero
JavaScript errors. The 3D render statistics reported 105 draw calls and 63
components. Those are rendering diagnostics, not performance benchmarks.

An initial forced `--use-angle=swiftshader` run timed out while taking a 3D
screenshot. A subsequent normal GPU-selection run succeeded. This is recorded
as a test GPU-configuration limitation, not a confirmed exporter defect. The
mobile inspector covers much of the drawing; that image demonstrates control
layout, not a clear mobile rendering of all 3D geometry.

The captures are evidence for this exact generated document. Subsequent host
changes, such as synchronizing the outer tab with built-in view changes, are not
retroactively represented by these images. Numerical or manufacturing signoff,
full native KiCad parity and model-geometry accuracy are not established.
