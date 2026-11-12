# Imported Fabrication Net Comparison: 4.8.3 Source Validation

Release association: **4.8.3**. This is recorded local
source/native validation, not a hosted release CI pass, installed update or
public-asset verification.

## Scope

The manufacturing package now exposes **Fab net compare...** in DFM/DFA Studio
and **Fabrication net compare...** in Manufacturing Readiness. A native guided
reference export and two-input comparison run asynchronously without modifying
PCB files. Sortable findings retain full original net groups and endpoint maps.
JSON, HTML, CSV and readable text derive from the same source-bound report.

Exact case-sensitive reference/pin membership, not matching net names, defines
correspondence. A merged observed group is one short finding even if it joins
nine original nets; a reference partition split across observed groups is an
open. Missing/extra endpoints and ambiguity remain separate coverage evidence.

The parser supports bounded strict JSON and a conservative IPC-D-356 subset:
317/327/367, ASCII CODE 00, UNITS CUST 0, and supported NNAME aliases. Mechanical
features and vias are counted separately. Potentially truncated/colliding names,
unsupported units/transforms and unknown records cannot establish `MATCH`.

`MATCH` means only a complete independently reviewed imported partition match.
`fabrication_verified` remains false. The operator's CAM-independence confirmation
is not authentication. Identical inputs cannot establish independent evidence.
No Gerber/Excellon copper reconstruction, physical electrical test or fabrication
approval is implemented. Existing native DRC/jobset release gates remain separate.

## Source safety

Native reference export runs the originating KiCad CLI on a private saved-PCB
copy. Its receipt records source/output SHA-256, native version and UTC, with
`design-netlist` basis. It is not a manufacturing-copper extraction. Existing
reference/receipt paths are not overwritten. Timeout/cancellation stops only the
owned CLI process. Atomic report publication rechecks sources and protects them
against output aliases.

When a native receipt exists, every comparison validates its output hash and,
when an active board context is supplied, the exact saved-board hash. Missing
receipts display `UNVERIFIED` rather than implying correspondence with the active
PCB. Receipt bytes are included in freshness and overwrite protection. Changed
inputs, cancelled work and closed windows cannot enable stale report export.
Large GUI lists/details are explicitly capped; complete exports remain available.

## Validation

Windows checks used Python 3.11, native wx and KiCad CLI/Python 10.0.6:

- Full manufacturing suite: 153 passed, 21 skipped. Skips are not acceptance.
- New fabrication UI under KiCad's own Python/wx: 8 passed.
- Core parser/partition tests cover renumbering, short/open groups, no-connect
  isolation, duplicate/truncated identities, malformed/oversized inputs, aliases,
  source hashes and incomplete coverage.
- Native reference export of KiCad's public PIC programmer demo preserved the
  original PCB hash. The actual exported IPC file was parsed and deliberately
  mutated in two separately labelled tests: GND/VCC merged to observed `168`
  produced one short; one GND endpoint split to `9001` produced one open.
  Remaining IPC name ambiguity stayed incomplete. These are synthetic mutations
  of a native export, not real independent CAM extraction or fabrication defects.
- The packaged generic JSON example has 18 shared pins and nine design nets
  merged to one observed group `168`: one short, zero opens. Its provenance is
  explicitly synthetic; all four report formats retain the group and pin map.
- Native reference, CLI and report tests cover cancellation, input drift, receipt
  tampering, wrong-board receipts, source/output alias protection, HTML escaping
  and spreadsheet-formula escaping.

A legacy native DFM controller run on the PIC demo passed 11 tests but failed a
fixture-specific count assertion: it returned five warnings rather than the
expected synthetic fixture's two errors/two warnings. That run used the wrong
fixture for that assertion; the baseline was not changed. Native reference and
new fabrication-dialog checks were validated separately. Live editor cross-probe
and actual vendor-CAM dialect qualification are not established by these tests.

See the [workflow and limitations](../../manufacturing_readiness_plugin/FAB_NET_COMPARE.md),
[offline help](../../manufacturing_readiness_plugin/fab_compare_help.html) and
[CLI guide](../../manufacturing_readiness_plugin/DFM_CLI.md#fabrication-net-comparison).
Primary reference export behavior is documented by
[KiCad CLI](https://docs.kicad.org/10.0/en/cli/cli.html) and the
[native writer source](https://docs.kicad.org/doxygen/export__d356_8cpp_source.html).
