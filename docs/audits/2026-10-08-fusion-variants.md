# Fusion and Variant Manager validation

Windows, KiCad 10.0.6 bundled Python 3.11.5; source checks also use Python 3.14.

| Check | Observed result |
|---|---|
| Shared regressions | 336 passed, 77 explicit skips, 150 subtests passed. |
| Fusion regression discovery | 225 tests completed, 69 opt-in skips; zero failures. |
| Fusion native saved files | Three fixtures passed: Board Only import with isolated nets and preserved target bytes/parity/DRC, overlap rejection, standalone schematic materialization/import. |
| Fusion native source selector | Three native GUI/control tests plus seven imported section regressions passed: repeated child occurrence resolution, scope override, board-only dispatch, viewport/busy guard, independent Apply Review dispatch. Dialog answers are supplied by tests; this is not a manual editor session. |
| Variant Manager | Nine backend regressions plus native hierarchical serialization/BOM and native wx workspace tests passed (11 total, no skips in the opt-in run). |
| Candidate PCM payloads | All 19 packages passed official schema, independent action registration/entrypoint, icon and Python syntax checks. |
| Isolated wheel | Eleven CLI entrypoints and bundled report/resources checks passed. |
| Disposable installation | All 19 packages installed into a separate KiCad directory. Variant Manager's extracted standalone window opened; its icon bundle and native Windows small/big icon handles were present. |
| Documentation | Source guide/image links and icon catalogue validated; shipped Variant Manager capture inspected. |

Fusion's synthetic sheet-list benchmark used 100 occurrences of one schematic
with 20 symbols. Three-run medians were 1.983 s for full import discovery and
0.024 s for the lightweight catalogue. This is a scope-listing measurement;
native acceptance remains uncached and whole-merge speed is not established.

Variant Manager's generated resistor fixture verifies 22k+DNP versus retained
10k+populated states in named native BOM exports, accepted root/child netlist/PDF
serialization and unchanged PCB bytes. Its native window checks comparison,
cross-selection, staged-change rows and source-project invalidation at 1360×900
and 1000×800. The screenshot shows a generic project location and captures only
the generated test window. It is an assembly-state overlay over saved envelopes,
not a regenerated footprint or routed board.

Applying variants or Fusion candidates still requires closed target editors,
fresh input hashes and backups. Unsupported overrides/geometry, unresolved
reference matches and reused-instance promotion conflicts remain explicit.
Linux/macOS native GUI compatibility, every connected-editor workflow and
manufacturing qualification are not established by these checks. The full CI
matrix is a release gate in addition to this local evidence.
