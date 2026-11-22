# WayriCAD 4.8.9

## Review

- Pin the official KiCad WebView 1.1.1 full ESM and license notices. It includes
  the saved back-side pad correction adopted by KiCad Online 0.12.105.
- Rotate a PCB or schematic while keeping comment pins and regions in saved
  coordinates. Rotation does not edit the source or grant posting authority.
- Fix initial native WebView layout so 3D starts with a usable viewport.
  Verified native back-side pad selection on an asymmetric two-pad fixture,
  plus publish, anchor readback and deletion refresh on the dedicated live
  GitHub test issue. This does not qualify all providers or operating systems.

## Assistant

- Optional local Ollama planning, editable inputs and explicit Run approval.
  Result explanations cite hash-verified artifacts and cannot change tool status.
- Add fitted nominal component counts, saved copper areas, steady thermal board
  screening, draft power trees and series-path discovery.
- Run reviewed PI, SI and thermal study files and built-in EMerge research
  examples with a prepared runtime. Model downloads and autonomous layout
  edits are not supported. Review values and assumptions before execution.

See [Review verification](../review_comments_plugin/VALIDATION.md) and the
[Assistant guide](../suite_assistant_plugin/README.md) for evidence and limits.
