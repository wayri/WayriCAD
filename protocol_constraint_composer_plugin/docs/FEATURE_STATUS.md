# 0.3.1 feature status — implementation is not host acceptance

| Requested area | Implemented in this delivery | Still not complete |
|---|---|---|
| Matrices and effective values | Existing inline matrices, CSV, scope and ownership protection retained. Added a native-resolution handoff that verifies real native selection and dispatches an existing menu action. | A full embedded native effective-value matrix, complete overlap resolution and native clearance heatmap are NOT implemented. Offline inspection remains a conservative subset. |
| Team constraint catalogs | Immutable content-addressed shared-folder catalog; explicit read-only HTTPS mirrors; version/digest checks; project pins; publish confirmation; controlled definition imports. | No hosted authenticated service was deployed. No background polling or arbitrary schema/code migrations. Schema upgrades fail explicitly rather than execute code. Existing instance migrations remain explicit. |
| Component-bound regions | Lines, arcs, circles, curved fp_poly paths, multiple outer islands and nested holes; same-island pair clearance; opt-in snapshot sync; owner/name/UUID/geometry/rule-state guards. | Exact native serialization, native move/flip semantics and interactive library-update behavior remain unaccepted. Source edits must be saved/reloaded; this is NOT a live canvas observer. Geometry preflight uses sampled arcs, not an exact native predicate engine. |
| Hierarchy / native inspection | Guarded access to native clearance/constraint resolution for actual open-board selections; staged-versus-open warning; explicit unknown offline outcomes. | Native menu dispatch is untested here. Native values are shown by KiCad, not read back into a universal embedded resolver. |
| High-speed constraints | Declared pass-through graph, path ambiguity checks, per-net fromTo rule generation, explicit ps budgets, branch warning, manual generated-rule protection. A genuine 2-D quasi-static finite-volume/CG line field solver adds C, impedance, delay and convergence checks. | The graph is logical connectivity, not arbitrary routed-copper extraction. No automatic active-device connectivity inference, topology synthesis, 3-D via extraction, full-wave SI/PI, loss or dispersion sign-off. |
| Cross-probing | Native selection callback preferred over selected flags; UUID enumeration extended to footprint zones; single-item focus hook; stale-board guard; native JSON evidence with hashes and stale-workspace warning. | Native callback behavior needs host acceptance. Flag highlighting is not the native selection manager. No all-object coverage guarantee, multi-object zoom fit, or cross-schematic probing. |
| Manufacturing/team review | Optional encrypted Ed25519 keys; external trusted public keys and approver roles; signed content snapshots; threshold/rejection decisions; protected-head anti-rollback option; policy-gated offline apply. | Trust proves key control under an administrator's registry, not legal identity. No accredited fabrication database, standards qualification, hosted IAM or complete organization governance. Ordinary local apply remains available; external release controls must enforce policy. |
| User experience | New native engineering/team pages, curved/multi-loop preview, scrolling BGA dialog with fixed actions, wrapping header, cancellation for field calculations, actual-host screenshot runner. | No rendered wx screenshot or real DPI/user-flow acceptance was possible here. Xpedition-equivalent usability is NOT demonstrated. |

## Documentation and help added in 0.3.1

Complete help coverage for the shipped workflows/catalog, native searchable Help,
F1 routing, contextual Help buttons and tooltips, eight labelled source-derived
UI renders, a searchable HTML handbook, and illustrated PDF/Markdown editions.
The browser handbook was exercised in real Chromium; native wx Help/F1/image
behavior remains unaccepted. See HELP_COVERAGE.md and TEST_REPORT.md.

## Release gate

Core regression tests and package checks are executed separately from native
acceptance. The current acceptance report is **INCOMPLETE**, not passed.
Missing runtime checks and manual checks remain visible. See `ACCEPTANCE.md`.
