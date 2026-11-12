# WayriCAD 4.8.3

## Release Scope

This document describes the 4.8.3 scope and recorded local validation. Published
source identity, hosted CI results and artifact hashes are recorded in the
attached `validation-4.8.3.json` release receipt; local test results below are not
a hosted CI pass. The suite retains 27 independently installable packages;
unchanged tools retain their existing capabilities and limitations.

## Shared Steady 3D Electrothermal Studies

- A shared rectilinear finite-volume solver resolves volumetric current, Joule
  heat and steady conduction with declared temperature-dependent resistivity,
  convection/radiation and Kelvin-consistent Seebeck/Peltier coupling. Explicit
  electrical contacts, thermal boundaries, material validity and conservation
  diagnostics remain part of the study contract.
- Heater Designer adds rigid, flex, rigid-flex and free-foil constructions,
  editable/custom material inputs and an offline original-cell 3D result viewer.
  Its automatic geometry adapter supports **one foil layer** and rejects
  unmodelled vias; it does not silently convert an arbitrary multilayer board.
- Quick PI and QuickTherm open the same explicit solid study and provide CLI
  entry points. Existing board/layer screens remain separate, not replaced by
  inferred 3D construction or guessed material properties.
- Quick SI adds reviewed, source-bound XYZ temperature mapping for **DC** route
  resistance and optional declared I-squared-R loss. Every original route
  section needs valid mapping; unknown/outside/void samples are rejected.
- Planar Magnetics maps primary trace losses into the shared multilayer thermal
  kernel and iterates local copper resistance for current or resistive DC
  voltage drive. Core loss stays separate unless explicit board-entering heat
  and an area/layer contact are provided. Native material/boundary forms, layer
  maps, cancellation, freshness guards and CLI evidence are included.

Native Heater and Quick SI launches support independent scientific-runtime
provisioning rather than relying on another plugin's environment. For standalone
solid-study CLI use, the Python distribution declares the NumPy/SciPy dependencies
through `wayricad[electrothermal]==4.8.3`; the `si` extra also declares SciPy.
Use the appropriate extra for direct source/wheel CLI work. These are dependency
and provisioning contracts, not a claim that a local installation was performed.

**Limits:** no 3D transient, CFD, contact-resistance or bending/stress solution;
no mature/qualified continuum Thomson treatment. The heater adapter is single
foil, the magnetics screen excludes via/pad Joule heat and loaded secondary
windings, and no core thermal properties are invented from material names.
SI feedback does not automatically re-solve high-frequency loss, impedance,
dielectric drift, crosstalk or eye diagrams. No measured thermal accuracy or
hardware safety approval is established.

See [heater construction/examples](../heater_designer_plugin/THERMAL_3D.md),
[shared equations and limits](../wayricad_runtime/THERMOELECTRIC_3D.html),
[SI workflow](../signal_integrity_advisor_plugin/ReadMe.md) and
[magnetics thermal study](../planar_magnetics_plugin/THERMAL_STUDY.md).

## Review And Offline Export

- Review and Portable Web Export independently bundle the **official KiCad
  WebView 0.6.0** distribution with MPL-2.0, dependency notices and exact asset
  pins. The verified archive SHA-256 is
  `668f973db5e931ff32a68a7ee2dfd178d54d0be25ff47b24a5b460681a6d28a4`.
  Integration-authored manifests are not misrepresented as upstream receipts.
  Dirty working sources and the unpublished 0.7 candidate are not the release pin.
- Review uses public saved-selection/camera APIs, deferred pane creation and
  stale/closed-load guards. Comment authority remains exact-source/scope-bound;
  exploded geometry cannot display assembled-position comment markers.
- Portable Export adds exact part/net lookup, ambiguity rejection, original-field
  inspection and public viewer controls without duplicating layer/camera state.
  Saved labels remain inert text; progress imports are bounded and validated.
- Export retains the exact preview bytes, rejects stale scans and source aliases,
  distinguishes original/bundled hashes after model-path rewriting and uses
  unique atomic output staging. Offline documents do not request external data.

**Limits:** Review still has incomplete live-provider/native-editor acceptance;
mocked responses or a native-channel stub are not live publication evidence.
Saved source connectivity is not native ERC/netlist validation. Hidden power
pins, buses and repeated-sheet instances retain upstream limits. Unresolved 3D
models use stand-ins; rendering depends on GPU/driver/browser configuration.

See [Review](../review_comments_plugin/README.md),
[Portable Export](../portable_web_export_plugin/README.md) and
[actual screenshot provenance](../portable_web_export_plugin/SCREENSHOT_PROVENANCE.md).

## Fabrication Net Comparison

- Manufacturing Readiness and DFM/DFA Studio provide a guided read-only
  reference/CAM comparison, plus `fab-reference` and `fab-compare` CLI commands.
  Inputs are bounded strict JSON or a conservative IPC-D-356 subset.
- Exact case-sensitive component/pin partitions identify grouped shorts/opens,
  even when CAM net numbers differ. One observed group joining nine design nets
  is one short group, not a fabricated 36-pair error list. Full original names
  and endpoint maps remain available.
- Native reference export uses a private saved-board copy and a source/output
  hash receipt with `design-netlist` basis. Receipt checks bind reference and
  saved-board bytes when available; absence remains `UNVERIFIED`.
- Background comparison/reference export, cancellation and source/result guards
  keep stale evidence from export. Sortable/capped native views retain complete
  canonical evidence. JSON, HTML, CSV and grouped TXT exports share provenance,
  hashes, alias protection and atomic writes; CSV formula triggers are escaped.

**Limits:** no Gerber/Excellon copper reconstruction or physical open/short test.
`MATCH` is a complete independently reviewed **imported partition match**, never
fabrication approval; `fabrication_verified` stays false. Missing/extra pins,
unsupported/truncated identities, incomplete coverage and self-comparison cannot
establish MATCH. A native design reference is not independent CAM evidence.
Existing native DRC/jobset and manufacturing-release gates remain separate.

See [workflow and synthetic examples](../manufacturing_readiness_plugin/FAB_NET_COMPARE.md)
and [installed HTML help](../manufacturing_readiness_plugin/fab_compare_help.html).

## Recorded Local Validation

These are local Windows/Python 3.11 receipts, with native checks using KiCad
10.0.6 where specified. Counts are separate suites/reruns, not additive totals.
Skipped tests are not passes or platform compatibility evidence.

| Area | Recorded evidence |
|---|---|
| Shared thermal/material/report/CLI/SI feedback focus | 73 passed |
| Native shared thermal controller | 5 passed; embedded WebView intentionally disabled |
| Broader heater, PI, Therm, SI and magnetics suites | Detailed counts, skips and environment-specific reruns in the thermal audit |
| Review Python / Node | 457 passed, 6 skipped / 36 passed |
| Portable Export Python / Node | 15 passed / 4 passed |
| Manufacturing suite | 153 passed, 21 skipped |
| Native fabrication dialog | 8 passed |
| Full local root suite | 1,159 passed, 147 skipped; exit code 0; Windows COM diagnostic noted below |
| Browser checks | Original-cell thermal fields/probes and public-demo review/export rendering; desktop/mobile checks with the scope recorded in audits |

Receipts and unresolved limits:
[thermal integration](audits/THERMOELECTRIC_3D_IMPLEMENTATION.md),
[WebView integration](audits/WEBVIEW_060_INTEGRATION.md), and
[fabrication comparison](audits/FAB_NET_COMPARE_IMPLEMENTATION.md).
They preserve the legacy DFM wrong-fixture count failure, initial runtime/backend
limitations and GPU-configuration timeout rather than relabelling them as passes.
Disposable candidate-package checks are not final 4.8.3 public-release evidence.

No all-OS native qualification or general KiCad 11 acceptance is claimed.
Actual browser screenshots retain their existing capture provenance/privacy
scope; a browser rendering is not a live editor, measured hardware or vendor CAM
qualification. Consult the attached release receipt for hosted CI and public
artifact identities rather than inferring them from these local checks.

## Known Limits

The full local root suite completed with **1,159 passed, 147 skipped and exit
code 0**, while emitting a non-terminating Windows COM `0x8001010d` diagnostic
during wx event yielding. Its global-context cause remains unresolved; isolated
reproduction checks do not establish a fix. This result is not native embedded
WebView or running-editor qualification, and no crash fix is claimed.

Two pre-publication audit findings were corrected: the shared solver selects
the supported SciPy conjugate-gradient tolerance keyword (`rtol` or legacy
`tol`), and Heater/Quick SI declare their scientific dependencies for independent
managed launches. Standalone extras are described above. These corrections do
not broaden numerical model coverage or establish an actual dependency install.

The thermal, high-frequency, fabrication and native-platform limits above remain
in force. MATCH is not fabrication approval; there is no Gerber reconstruction,
3D transient/CFD or automatic full high-frequency temperature feedback, and no
all-OS native or general KiCad 11 acceptance is implied.
