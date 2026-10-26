# WayriCAD 3.6.35 release evidence

## Workflow and model boundaries

The common return selection is visible; optional sampling, multiple domains,
endpoint annotations and reference overrides are collapsed. A ground-like name
is a navigation suggestion, not electrical evidence. Shared pad-discovery helpers
preserve IDs and require explicit acceptance.

PI's geometric review follows the Setup net until manually overridden. The
guided DC editor shows all return mappings together, permits shared multi-pad
units, and preserves existing independent-loop numerical options and unrelated
groups. JSON remains available as an advanced representation. SI caches its
terminal inventory and ranks the chosen source/receiver's footprint pads first;
case-wide return assignment clears obsolete case-specific return pin roles.

No solver equations, sampling defaults or return-current assumptions were
changed. Geometric coverage remains separate from DC conduction and SI
impedance reference selection. Unknown evidence is not upgraded to a pass.

## Native and regression checks

Windows with KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2:

- Integrated PI run: 54 tests passed in 11.340 seconds, normal exit. Guided
  geometric and DC setup, duplicate identities, stale-input handling, startup,
  shared-return calculations and batch behaviour are covered.
- SI run: 21 tests passed in 5.062 seconds, normal exit. Controls, advanced
  collapse, explicit confirmation, endpoint-role invalidation, common study
  returns, existing selection contracts and actual saved-board SI analysis
  are covered. Source board bytes remain unchanged.
- Four shared helper tests pass without native KiCad. Names are ranked only
  for explicit confirmation; endpoint filtering retains duplicate pad IDs.

The final combined PI/SI/helper run passed all 79 tests in 14.983 seconds with
normal process exit, including the final collapsed controls and bounded labels.

A synthetic saved PCB with eight straight tracks and a filled B.Cu return zone
was reviewed through the actual PI worker. It reported eight checked tracks,
zero warnings and zero unknowns. This is sampled geometric evidence, not proof
of a complete electrical return loop. The native application exited normally.

## Screenshot provenance

PI `help-return-setup.png` shows that actual synthetic worker review.
`help-return-ground.png` and `help-return-rails.png` show synthetic staged
multi-rail and multi-pad inputs, not solved power results. SI
`help-return-setup.png` shows a synthetic saved route with declared 50 Ω and
effective permittivity 3; absent filled return zones remain unknown. Captures
use native controls and ordinary application lifecycles. No private designs,
local paths, numerical edits or pixel alterations are included.

Earlier release binaries and tags are preserved. Candidate package metadata is
held back until its release downloads are published and verified.
