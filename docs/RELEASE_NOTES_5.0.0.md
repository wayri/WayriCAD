# WayriCAD 5.0.0

## Power integrity and Assistant

- Quick PI adds a board-first result selector, smoother field maps, pinned
  probes with linked table rows, and a resistance profile along representative
  routes. Probes retain their board coordinates when a scenario is rerun.
- Set a percentage voltage tolerance, optionally show exact voltages, and
  review width guidance for supported failing or near-limit traces.
- Define separate load groups on the same connector or footprint. The Batch
  window runs multiple saved-board rail cases and compares their status, drop,
  and loss. Explicit return groups remain available.
- Quick PI opens with editor following off. Optional live copper checks pause
  while PCB Editor has focus and resume when Quick PI returns to the foreground.
  Analysis workers run with lower scheduling priority.
- WayriCAD Assistant uses a local fuzzy command matcher. It can prepare reviewed
  multi-net DC batches and lumped RLC load-step studies from explicit inputs.

## Editor integration and review

- Updated plugins follow the originating KiCad editor and use supported
  selection, highlighting, and saved-board refresh workflows. Unsaved geometry
  remains limited to the actions that explicitly support editor snapshots.
- Quick SI and Trace RLC surface missing return-path and via-transition evidence.
  Trace Refiner exposes per-proposal validation evidence for review.
- Component Arranger adds conflict details and bounded placement trials. Quick
  EMerge remains beta and provides a larger antenna and result viewport.
- Quick EMerge adds the upstream CORVID iterative and SPARTA direct solver
  selectors with EMerge 3.0.10. New runtime candidates pass compatibility
  checks before activation. GPU and Hybrid availability depends on hardware
  and drivers.

## Validation and model limits

A native KiCad 10.0.6 test verified that Quick PI resumes the same scenario
after an unsaved edit. A public Marble PCB copy completed four independent
2.5D DC rail cases. The Assistant reproduced the same voltage drops and
completed a separate lumped RLC transient. These are simulation checks on
declared setups. Supported shared-return cases require reviewed contacts,
and transient R/L/C must be supplied. Dense-board editing latency has not
been benchmarked.

[Quick PI guide](../quick_pi_plugin/README.md) ·
[Assistant guide](../suite_assistant_plugin/README.md) ·
[Quick EMerge guide](../quick_emerge_plugin/README.md#corvid-and-sparta) ·
[Installation](INSTALLATION.md)
