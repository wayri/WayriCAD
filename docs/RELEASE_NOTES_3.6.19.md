# WayriCAD 3.6.19

Performance and interaction improvements for the WayriCAD suite. Refresh the
WayriCAD repository in KiCad Plugin and Content Manager to update.

- Reduce repeated IPC reads during bounded planning operations and selection
  polling. Keep source checks fresh with bulk protobuf fingerprints.
- Add searchable multi-select dialogs to analysis return nets, thermal mounting
  contacts and Copper Balancer layers, plus visible search for long RLC inputs.
- Run saved-board Quick SI analysis in a cancellable subprocess. Reject results
  after input, saved board or rule changes.
- Share PI/SI return-path evidence with explicit terminals, sampled copper
  coverage and return-via contact details; retain unresolved geometry.
- Use targeted, confirmed PCB selection with restoration on failure. Add PI
  additive selection, SI route/return/reverse actions, and multi-component
  thermal synchronization.
- Index display picking, batch Matplotlib copper drawing and update thermal
  selection overlays without rebuilding the field. Cache and cull Trace Refiner
  preview geometry (plugin 0.1.1).

See the [performance audit](audits/performance-coverage-2026-10-15.md) for timings,
reproduction commands and unmeasured workflows. Numerical acceptance checks,
source freshness and board-write review gates remain in force. No new compiled
backend dependency is introduced.

The 17 IPC packages advance to 3.6.19 and Trace Refiner to 0.1.1. Fusion 0.9.8,
Variant Manager 0.6.1 and Silkscreen Labels 0.2.0 retain their published bytes
and hashes. [Download installers and checksums](https://github.com/wayri/WayriCAD/releases/tag/v3.6.19).

The release uses source commit `74540698340a73f65ce3417e9c1fecc1d18f6de3`,
which passed all eight CI jobs. Uploaded assets were downloaded and compared
against local SHA-256 hashes before promoting the KiCad feed. Native GUI
validation targets Windows with KiCad 10.0.6; live-editor IPC navigation and
native Linux/macOS GUI remain unverified.
