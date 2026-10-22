# WayriCAD 3.6.25

The 17 IPC packages advance to 3.6.25. Trace Refiner advances from 0.2.3 to
0.3.0 and adds a separate pad/via endpoint-centering action. It moves only an
existing straight-track endpoint already touching one unambiguous same-net
copper pad or via. The default shift limit is 0.25 mm, with a permitted range
greater than zero through 2 mm. Actual gaps and uncertain contacts remain
unchanged, and native connectivity plus before/after KiCad DRC are required
before applying a proposal. Validation can repair KiCad's specific endpoint-
not-centered-on-via warning only for the reviewed track/via contact, and the
warning must disappear from the candidate; other existing errors remain
blocking. Detected tuning meanders remain protected.

Five other native packages keep their existing versions and 3.6.24 package
bytes. Silkscreen's public dense-board exercise reports 241/417 accepted on
Forsten FMCW3, 173/319 on Forsten VNA, and 170/182 on Marble; unresolved labels
remain unapproved. See the [dense-board audit](audits/SILKSCREEN_DENSE_BOARD_0.3.3.md)
for per-board limits and independent geometry checks.

On Windows with KiCad 10.0.6 and Python 3.11.5, the native Trace Refiner suite
passed 83/83 tests. The shared root suite passed 494 tests and 227 subtests, with
88 skips. All 23 PCM ZIPs passed package validation; full documentation checks,
the isolated wheel smoke test and the extracted Trace Refiner centering suite
(21/21) passed. The repaired via warning fell from one baseline finding to zero
candidate findings, and copied project/custom rules remained intact during
validation. Hosting and public download verification remain release steps.
