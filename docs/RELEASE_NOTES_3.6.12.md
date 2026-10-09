# WayriCAD 3.6.12

Refresh the WayriCAD KiCad PCM repository, update the installed tools and restart
KiCad. All 17 IPC packages move to 3.6.12 because each carries its own shared
runtime. Project Fusion 0.9.8 and Variant Manager 0.6.1 retain their existing
native packages and MIT licenses. The suite still contains 19 independent tools.

BoM Studio repairs whole-board mass and cost totals, quantity and pack-price
handling, consolidation by reviewed part keys, analytics and exports. Missing
values remain visible, and currencies are reported separately. Browser requests
recover cleanly from rejected input rather than leaving the interface stalled.
The wheel now includes and exercises the complete BoM web interface.

Constraint Studio keeps inspection, long findings lists and reviewed application
responsive. Repeated apply requests cannot overlap; closing a window prevents
late worker callbacks from reaching destroyed controls. The visual editor has
bounded bridge requests and explicit recovery. Existing staged snapshots,
source-hash checks and reviewed offline application remain in place.

Quick PI adds independently specified current sinks, supply voltage/current
budgets and per-sink voltage requirements to its 2.5D DC workflow. Current-budget
failure reports infeasibility; it does not simulate a regulator's current-limit
control loop. Existing single-load, current sweep and optional 3D workflows stay
available. The explicit R/L/C transient study models load steps and decoupling.
Shared-edge mesh subdivision avoids false electrical disconnections. Ideal
parallel-capacitor constraints retain stored inductor current across load and
resistance changes without amplifying numerical roundoff.
Steady electrothermal coupling transfers conductor loss to a thermal model and
feeds temperature-dependent copper resistance back into PI; lumped transient
coupling exchanges resistor dissipation with declared thermal RC nodes. See the
[electrothermal guide](../quick_pi_plugin/ELECTROTHERMAL.md) for model coverage,
input units and acceptance checks.

Quick PI and QuickTherm show continuous gradients within the solved field's
support. QuickTherm exposes a whole-board study action and prefers physical
board/layer fields when available. A contour interpolated from component
junction temperatures identifies its limited anchor hull; it does not claim a
whole-board surface temperature. Finite-volume fields include boundary cells
and remain clipped to the outline, cutouts and drills. Manual thermal values
and explicit field mappings survive reload of the same board; unique common
thermal field aliases are suggested without guessing ambiguous mappings.
An independent component power-step RC study is also available through
`wayricad-therm --transient` with explicit thermal resistance and capacitance.
Existing advanced spatial thermal transients, slots, probes and mesh checks
remain available.

For Windows errors launching `pythonw.exe -m venv`, the new source-checkout
[interpreter diagnostic](TROUBLESHOOTING.md#windows-all-ipc-environments-fail-before-the-action-appears)
checks KiCad's host configuration before plugin execution. It previews by
default; explicit repair requires KiCad to be closed and preserves a backup.

## Validation and limits

Windows source checks used KiCad 10.0.6 with its Python 3.11.5 runtime. BoM
Studio ran 1,257 tests: 1,255 passed and two optional Zstandard/OCP checks were
skipped. Its real local HTTP/DOM workflow verified totals, consolidation,
exports and request recovery. Constraint Studio passed 372 tests, native visual
editor startup/recovery and responsive large-report/apply checks. Shared new
numerical and workflow checks passed 70 portable tests with two native-only
skips and 59 additional subtests. The complete shared suite passed 397 tests
with 73 optional/native skips and 152 subtests. Quick PI passed 228 native tests
and 159 subtests; its portable suite passed 192 tests with 23 native/optional
skips and 159 subtests. QuickTherm passed 161 distinct native/portable tests,
with two optional skips and 81 subtests, including an actual whole-board window
workflow, manual grid edits, field restoration and ordinary closure. These
checks read disposable saved boards;
they do not establish every tool's live-editor workflow on every operating
system.

After the drilled-void review finding was fixed, the affected coupling,
workflow and native UI checks passed 40 tests and 40 subtests with a clean
process exit. The rejection preserves the original study input.

Transient regression checks passed 36 tests each on native Windows, portable
Windows and Linux scientific runtimes. A deterministic analytical projection
check reproduced the previous failure in 12 roundoff cases and passed all 12
after the fix. Conservation and thermal acceptance thresholds were unchanged.

The new steady electrothermal path uses the shared uniform-grid kernel and
circular plated barrels. It rejects unplated drilled holes, plated slots and backdrills; those newer
standalone QuickTherm capabilities are not silently substituted into coupling.
Transient PI and electrothermal models require explicit electrical and thermal
parameters. Their numerical balances and refinement checks are model evidence,
not measured-board qualification. Missing/unsupported regions remain unknown.
Plated drill-core air cavities remain unresolved by the uniform-grid coupling
approximation; its barrel conduction uses declared annular plating. Restricted
Windows test processes initially failed or stalled at native DLL/filesystem
access. The affected native engine and GUI checks passed outside that sandbox.
Native desktop operation on other platforms and KiCad 11 remain unverified.
