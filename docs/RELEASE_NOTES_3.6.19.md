# WayriCAD 3.6.19 — performance candidate

This source version is a development candidate. The public PCM feed remains on
published assets until a separately validated release is published.

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
