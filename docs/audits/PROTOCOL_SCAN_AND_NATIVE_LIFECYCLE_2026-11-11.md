# Protocol Scan and Native Lifecycle Checks

## Scope

Windows, KiCad 10.0.6, bundled Python 3.11.5, wxPython 4.2.2 / wxWidgets 3.3.2.
These are source-candidate checks, not an installed update, release, or proof of
live-editor IPC compatibility. No user PCB was changed. Temporary evidence stayed
on D:. Packaging, installation and dependency downloads were not performed.

## RLC Protocol Candidate

- Added bounded token/fuzzy/wildcard/restricted-regex discovery, scoped pair
  matching and physical section screening through the existing RLC engine.
- Explicit coverage includes RGMII, SGMII, DDR, parallel PCI, PCIe, SerDes and
  FPGA GTH/GTY/GTX/GTP. Family identities do not infer operating rates.
- Reports retain ambiguity, missing mates, unsupported geometry, targets,
  corrections, source fingerprints, UTC generation time and versioned schemas.
- Saved-board native extraction runs in a disposable process. Worker crashes,
  cancellation and timeout are controlled errors, not partial passing reports.
- Differential coupling is unresolved; no automatic coupled-Z pass or protocol
  compliance claim is made.

Checks performed:

```text
python -m pytest trace_impedance_plugin/tests tests/test_audit_native_lifecycle.py -q -p no:cacheprovider
77 passed, 2 skipped
python tools/validate_docs.py --source-only
Current user documentation and local illustrations validated (source only).
```

Tests include ambiguity, false-positive rejection, lane/hierarchy matching,
directional impedance suggestions, differential unknowns, omissions, malformed
rules/targets, cancellation, controlled native-worker failure, stale-source
rejection and CLI no-overwrite/exit-code contracts. The PDF test lacked
`reportlab`; the workspace-layout test required native KiCad/wx. Those two skips
are not passes. The separate native GUI probe below exercised window lifecycle.

`tools/verify_rlc_protocol_scan.py --output <scratch> --gui`, run using KiCad's
Python, generated a synthetic 12-net routed board with deliberately missing
physical stackup/reference evidence. The worker returned all 12 expected
candidates without a false passing result. The native parent/protocol windows
constructed, populated and closed successfully. The PCB SHA-256 was unchanged.
This is a lifecycle/unsupported-input check, not numerical solver qualification,
live cross-highlighting validation or a production-board timing analysis.

## Broader Lifecycle Audit

`tools/audit_native_lifecycle.py` uses separate bounded processes and two
open/close cycles. Source passes: Bulk Label Editor, Fanout Generator, Via
Stitching, Copper Balancer, Quick PI, Quick SI, Manufacturing Readiness, Extract
Pins, Heater Designer, Planar Magnetics, Mechanical Check, Harness Workbench,
Portable Web Export, Assistant and Embed3D. Installed Quick PI and Copper
Balancer also passed. Recorded fixture hashes were unchanged.

**Unresolved:** source and installed Constraint Studio reproducibly raise
`GetRowPos(): invalid row index` during startup. Native diagnostics place the
assertion in Windows accessibility querying wx grid coordinates. The exact
triggering lifecycle remains unresolved. Matrix-accessibility disabling and
row-label initialization-order experiments did not establish a reliable fix;
all those exploratory source changes were removed. Accessibility is not disabled
and assertions are not suppressed. No access-violation crash or hang was
reproduced in the completed bounded probes.

This is not complete suite coverage: EMERGE/Therm have separate prior evidence;
web/account-dependent and other unprobed entrypoints are not inferred passing.
No apply/commit, every-button, cross-editor or long-running solver coverage is
claimed by constructor tests.

## Retained Evidence and Storage

The local lifecycle receipt, per-process stage/exit logs, assertion stacks and
synthetic RLC receipt/report are retained in task-owned scratch. They are not
package assets and contain local paths, so are not published as screenshots or
repository fixtures. Lifecycle evidence occupied about 38.5 MiB; the protocol
fixture/report was under 0.1 MiB. At the audit checkpoint C: had about 6.22 GiB
and D: 180.64 GiB available. C: remains below the required 100 GiB reserve;
no local installation was attempted. No preexisting data was deleted and no OS
quota enforcement is claimed.
