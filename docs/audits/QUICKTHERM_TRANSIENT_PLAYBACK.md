# QuickTherm transient playback verification

Date: 2026-10-10. Scope: visible spatial-transient setup, air/vacuum boundaries,
native and exported heating playback, and schedule integration. This is source
and local candidate-package evidence; it is not a published release or physical
thermal qualification.

## User workflow

On **Board + results**, enable **Transient · watch board heating**. The multilayer
model and transient settings open together. Review stackup, conductivity,
emissivity, heat capacities, initial temperature, duration and maximum step.
**Power steps…** edits one switch per included source; advanced JSON retains
multi-event profiles with held steps or linear ramps.

After running, use **Play/Pause**, scrub the computed frame slider, or select
1×/5×/20× speed. Top, bottom and interactive 3D views retain one temperature
scale for the study. Probes, component power, junction estimates and limit
checks follow the selected frame. Camera movement survives time updates. Input
changes invalidate playback and exports; closing stops the timer. The HTML
report has equivalent computed-frame playback controls.

Air uses declared convection and radiation. Vacuum sets convection to zero,
disables airflow inputs and retains radiation/fixture conduction. Forced air
uses an explicit effective convection coefficient. These are thermal boundary
models; they do not solve fluid flow, residual gas or chamber view factors.

## Reproduction and screenshot provenance

[Native transient workspace](../../quick_therm_plugin/examples/quicktherm-transient-workspace.png)
is an unmodified capture of the standalone PCM package, not a mockup. It uses
the public `thermal-demo.kicad_pcb`, copied to disposable validation storage
with an explicitly assumed F.Cu/core/B.Cu stackup of 0.035/1.53/0.035 mm. The
original fixture and copied study PCB were hash-checked unchanged by analysis.
No personal paths, user boards or private network addresses appear.

Included invented sources: C1 0.20 W, C2 0.45 W, C3 0.10 W and J1 0.30 W.
C2 switches from multiplier 1 to 0 at 4 s. Duration is 10 s, maximum step 0.5 s,
initial/ambient temperature 20 °C, emissivity 0.8 and grid long axis 24 cells.
Assumed copper/dielectric conductivity is 385/0.3 W/(m·K), via plating 0.025 mm,
and volumetric heat capacity 3.45/1.8 MJ/(m³·K). Air uses zero prescribed airflow
with the implemented 5 W/(m²·K) convection approximation; vacuum uses zero
convection. No sink heat capacity is needed for this no-heatsink fixture.

Run `python tools/check_thermal_playback.py` with native wx/SciPy dependencies.
For a built PCM ZIP extracted independently, pass `--plugin-root` pointing to
its flat `plugins` directory. The check removes checkout paths from imports and
asserts that QuickTherm is loaded from that isolated package. It uses the real
service but invokes it synchronously for bounded UI verification; the separate
whole-board tests exercise the asynchronous worker.

## Checks actually performed

Environment: Windows, KiCad 10.0.6; native Python 3.11.5, wxPython 4.2.2 /
wxWidgets 3.3.2, NumPy 2.4.2, Matplotlib 3.10.8. Portable suite: Python 3.14.2,
NumPy 2.4.2, SciPy 1.17.0 and pytest 9.0.3.

| Check | Result |
|---|---|
| Complete portable QuickTherm suite | 187 passed, 22 native/optional cases skipped, 129 subtests passed |
| Native spatial solver, playback helpers and view interactions | 27 passed |
| Native whole-board UI / asynchronous worker regression | 4 passed |
| Isolated PCM native air/vacuum workflow | Passed power-step modal editing, actual wx timer advancement, pause/replay, slider events, probes, fixed scale, camera preservation, export, invalidation, close and source hashes |
| PCM validation | 19 candidate ZIPs passed schema, independent runtime/assets and syntax checks |
| Packaged help | Official document/image checks passed for all 19 candidate ZIPs, including the QuickTherm offline guide |
| Wheel | Built; isolated wheel smoke passed CLI, report assets, mechanical export, transient and electrothermal workflows |
| Documentation / JavaScript | Source documentation validation, interactive inline-script Node syntax check and `git diff --check` passed |

The native fixture stored 21 frames. Air initial/final peak board temperatures
were 20.0/55.92015 °C; vacuum was 20.0/56.42652 °C. Maximum discrete energy
residuals were 2.60e-14/2.78e-14 W. These numbers reproduce an assumed model,
not hardware accuracy. A study-wide scale also includes the earlier higher
peak, before C2 switches off.

The numerical tests compare switched air heating/cooling with an independent
analytical RC reference, and nonlinear vacuum radiation with a separately
integrated DOP853 reference plus time refinement. Short pulses and linear
ramps have explicit interval-energy checks. Integration lands on schedule
events and stored-frame decimation preserves them. Malformed and nonphysical
inputs are rejected rather than replaced with defaults.

## Verification limits

Skipped native/optional portable tests are not passes. Combining system pytest
with the native KiCad runtime encountered optional Gmsh DLL/capture and wx
teardown failures; that mixed-runtime run is not counted as a pass. Native
checks above ran separately. The native helper logs sandbox-denied optional
registry preferences to stderr so a second error modal cannot hold its event
loop; production optional solver preferences are also non-blocking.

HTML generation and script syntax were checked. Browser interaction with the
local report was unavailable under the browser's file-URL policy and is not
claimed as verified. Native playback and export were exercised.

The default full documentation command targets the published 3.6.12 feed and
could not validate those archives because this worktree has no local published
ZIPs. Source validation passed, and the same official packaged-document checks
were applied directly to every disposable candidate ZIP. No public feed was
changed to make the check pass.

The spatial board workflow first requires a solvable steady heat-rejection
path. Vacuum therefore needs nonzero emissivity or fixture conduction. Heat
capacities are declared assumptions; package die, plated-barrel and coating
storage are unresolved. Junction offsets use explicit massless RθJB. STEP
component solids are not loaded. Implicit stability and energy balance do not
establish time/mesh convergence; refine both separately before relying on local
hotspots or peak timing. Public package feed and published assets remain
unchanged.
