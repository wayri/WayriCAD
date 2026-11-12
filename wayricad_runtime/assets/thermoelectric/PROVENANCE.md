# Offline 3D renderer

Three.js 0.187.0, MIT license, from the official npm tarball:
https://registry.npmjs.org/three/-/three-0.187.0.tgz

Registry SHA-512 integrity:
`Qiu7R+Cmh8CstZsY1uJOSWnVlfo7ZtNLV7mF8Jltk3LB3AtDu9cRZlcnRKkAk8Y4z6KKw35z7Y7Urd7jWY8etA==`

Only the unmodified `three.core.js`, `three.module.js` and MIT license are
vendored. The report embeds those modules as data URLs so it has no external
network, CDN or browser installation requirement. `viewer.html` is project code.
The verified package currently has no minified renderer builds; its CommonJS
entry is a Node-only ESM shim and is intentionally not used.

## Help image

`help-heater3d.png` is an actual Chromium/WebGL rendering of the solved
`heater_designer_plugin/examples/3d-copper-flex-study.json` request, captured at
1440 x 1000 on 2026-11-13. It shows the original finite-volume cells, with the
foil layer selected. It is a browser result capture, not a native KiCad window
or measured temperature image. The matching image is
`heater_designer_plugin/help-3d-preview.png`. No private project data were used.
