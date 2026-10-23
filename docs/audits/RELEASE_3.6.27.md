# WayriCAD 3.6.27 release validation

This release packages the first-run Quick PI, board-view and Fanout changes at
`61d81309`, `12512284` and `f9a9c203`. Functional evidence includes 93 native
PI/render/report tests, 149 native routing/preview tests with 16 subtests, and
521 shared tests with 101 skips and 227 subtests. Selections overlap; these are
not independent qualification totals. Native checks used Windows, KiCad 10.0.6
and Python 3.11.5. See the linked performance audits for exact scope and limits.

The release candidate adds version metadata and documentation. Its exact source
must pass CI before publication. Package, isolated-runtime and download checks
are recorded below as they complete. Published PCM metadata stays on the prior
release until the new assets have been verified.

## Candidate checks

- All 23 PCM ZIPs passed official-schema, payload-syntax, entrypoint, icon,
  independent-runtime and SHA-256 validation. Bundled help and images passed
  documentation validation.
- The 17 IPC versions are 3.6.27. All six native ZIPs match their published
  3.6.26-release counterparts byte-for-byte and retain their package versions.
- The isolated wheel passed CLI imports, local Analytics API/assets, reports
  and mechanical-rules export checks. Version/inventory/package contracts:
  18 tests and 99 subtests passed.
- Independently extracted Quick PI passed 52 checks; Fanout passed 51, with
  zero skips in both selections. Every production Python file was verified
  against archive bytes: 101 files for Quick PI, 64 for Fanout. Loaded
  production modules came from the extracted archives, not source siblings.
- The Fanout live-timer test initially stalled because it assumed a fixed
  event-loop exit delay. The test now waits for actual preview completion and
  exits after queued callback work. The live-timer check and all 51 extracted
  Fanout checks then passed against the unchanged ZIP. Product code was not
  changed to resolve this harness lifecycle issue.
- Python archives exclude validation caches and private boards. Candidate text
  payloads were checked for the known private machine/project path identifiers;
  none were found. Existing screenshot provenance remains applicable.

These are Windows standalone native/saved-file checks with registration stubbed
outside PCB Editor. They do not qualify installed-editor IPC operation or native
DLL interpreter teardown. Numerical and routing limitations remain those in
the functional audits; no solver or geometry control changed during packaging.

## Publication procedure

Publish the exact candidate commit only after all eight of its CI jobs pass.
Attach all 23 ZIPs, resources, wheel, source archive, candidate feed, notes and
SHA-256 manifest. Download every asset and compare its bytes with the validated
candidate, then promote the public PCM feed and verify its descriptor and every
package URL/hash. Existing published versions and Git history remain intact.
The release page records the source commit and its successful CI run.
