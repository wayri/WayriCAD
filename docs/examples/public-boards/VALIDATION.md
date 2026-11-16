# Validation Scope

Recorded on Windows with KiCad 10.0.6 / Python 3.11.5. Producer version 4.8.5;
the exact source revision, source hashes, module identities, timestamp and inputs
are recorded in each case's execution receipt.

## Performed

- Six actual native saved-board runs: PI, SI and steady thermal on Olimex P4
  and Marble. No source board, saved stackup or zone fill was changed.
- Five generator/collection tests: pinned input rejection, path containment,
  saved-sidecar custody, all-or-nothing failure behavior, output identities,
  finite JSON, PI current/energy balance and thermal energy balance.
- Focused portable result/report/CLI regressions: **94 passed, 3 skipped**.
  Existing scientific dependencies and bundled ReportLab were reused; no new
  dependencies were installed. The skips are opt-in native reproduction and
  adapter tests for the older synthetic fixtures, not passes. The six new
  native cases and actual reader checks were run separately.
- Actual KiCad Online reader acceptance for all six outputs, including plot
  counts and saved-source bindings. [Adapter identities](viewer-adapters.json)
  identify the exact local modules; they do not establish every extension host.
- Site catalogue/controller/product-page tests: **19 passed**. The actual
  catalogue also passed validation against all six staged PCB/result hashes.
- Browser source preview using the published WebView 0.7.0 SDK: both real-board
  PI cases reached matching source association and registered 3D PCB status;
  steady thermal maps and SI route-impedance plots loaded. An empty plot probe
  correctly reported no saved value instead of inventing one.
- Source documentation and image validation, plus Git whitespace checks.

## Not Established

No claim is made for numerical mesh refinement, real component dissipation,
fabrication stackup accuracy, hardware correlation, protocol compliance or
general thermal 3D placement. Steady thermal placement is a known 0.7.0 adapter
limitation, explicitly retained in the guide. SI eyes remain unavailable.

The browser viewport override did not take effect in this environment; a narrow
mobile rendering check is **not established**. Desktop layout was inspected.
The local preview is not a full Jekyll build. Public deployment and hosted CI
must be checked separately; a source commit or local screenshot is not proof
of either.
