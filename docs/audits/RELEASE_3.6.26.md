# WayriCAD 3.6.26 release validation

The performance/trace fixes at `5825683ca982a0572ae6dc82f78afb3a8c52aad4`
passed all eight GitHub CI jobs before release preparation. This release adds
version metadata and release documentation; the release candidate receives its
own exact-source CI run before publication.

Functional source evidence: 503 shared tests passed, with 89 skips and 227
subtests; native Quick PI/view checks passed 46/46; native Trace Refiner backend
checks passed 73/73, UI/UUID checks 12/12 and cached-preview checks 9/9. Some
UUID tests appear in both Trace Refiner selections. Native tests used Windows,
KiCad 10.0.6 and Python 3.11.5. See the linked performance audits for measured
scope, source hashes and unchanged electrical results.

## Candidate packaging

- All 23 PCM ZIPs passed official schema, Python syntax, entrypoint, icon,
  independent-runtime and SHA-256 validation. Their bundled documentation and
  images passed full documentation checks.
- Five unchanged native ZIPs match the previously published 3.6.25 bytes exactly.
  The 17 IPC packages are 3.6.26; Trace Refiner is 0.3.1.
- The 3.6.26 wheel passed all isolated CLI imports, Analytics Studio local API
  and assets, report generation and mechanical rules export checks. The initial
  restricted run could not access localhost; the authorized loopback-enabled
  run passed without changing code or tests.
- Extracted Quick PI passed 15 focused native checks, and extracted Trace Refiner
  passed 11. Test support was staged beside each independent package; runtime
  modules were imported from extracted ZIP contents rather than sibling source
  installs, and their bytes were checked against archive members. These are
  standalone native/saved-file checks, not a connected editor acceptance claim.
- Wheel and source contents were checked for private validation folders; release
  notes and performance audits are included in the source archive. No private
  project, validation cache or local machine path was added to source changes.
- The candidate feed uses LF bytes, and its package/resource descriptor hashes
  were checked before staging. The public feed stays on the previous release
  until the new assets have been published and independently downloaded.

## Publication checks

The release page records the exact source commit and its own successful CI run.
`SHA256SUMS.txt` accompanies the attached ZIPs, wheel, source archive, feed and
notes. Publication verifies every uploaded asset by downloading it and comparing
its bytes with the validated candidate, then checks every package URL/hash and
the repository descriptor before promoting the public PCM feed. The public feed
is verified again at its promoted commit; raw-URL caching can delay visibility.

Version-only runtime/metadata substitutions were checked against the preceding
validated source. No numerical algorithm, geometry control or solver tolerance
changed during release preparation. Native host/OS limits in the functional
and performance audits continue to apply.
