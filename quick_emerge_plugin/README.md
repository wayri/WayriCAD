# Quick EMerge

Testing beta native electromagnetic workbench for KiCad, version 3.6.43.
The workbench provides patch/PCB-coupon templates and a **saved-PCB rule-area
mode** that simulates polygon-clipped two-layer copper. Templates use the PCB
as context only; rule-area mode imports actual saved copper and explicit
dielectric separation. Components and the PCB outside the enclosure are omitted.

![Native field viewport with linked probes and inspector](help-workflow.png)

The screenshot shows a coarse EMerge 3 smoke run, not a converged antenna
design. Local interpreter and output paths were replaced with generic paths;
numerical data were preserved. See [capability coverage](CAPABILITIES.md) for
the complete integration scope, including capabilities still to be implemented.

## Install the testing beta

Download the Quick EMerge PCM ZIP from [the 3.6.43 beta prerelease](https://github.com/wayri/WayriCAD/releases/tag/v3.6.43-beta.1), then use KiCad Plugin and Content Manager's **Install from File** and restart PCB Editor. This is an independently installable testing package; the stable PCM feed remains unchanged. Enable the KiCad API; the launcher provisions desktop dependencies separately. See [runtime setup](https://github.com/wayri/WayriCAD/blob/v3.6.43-beta.1/wayricad_runtime/RUNTIME_SETUP.md). First-open solver setup is separate from the desktop/IPC host dependencies.

## Run from source

The desktop Python needs Python 3.10+, wxPython, Matplotlib and NumPy.
On first open, the dependency manager automatically creates an isolated solver
environment and installs the latest available **EMerge 3+** release and its
dependencies. It includes 3.x prereleases because upstream's stable channel is
currently 2.x. Python 3.10–3.13 must already be available; on Windows the manager
also discovers Python through the Python launcher and installed KiCad runtimes.
Packages are installed into the new environment, never into KiCad or another
tool's interpreter.

```powershell
python -m quick_emerge_plugin --board C:/Projects/Example/board.kicad_pcb
```

Wait for the visible dependency setup to complete, or select a manual solver
Python override. Select a run folder with at least 1 GiB free and a model.
Enter dimensions in **mm**, frequency in **Hz**, and reference impedance
in **ohms**. Material permittivity is an explicit real relative value. Review
the native 3D geometry and numbered feed locations with **Preview setup**,
then select **Run EMerge**. Mesh generation and solving run in a separate
process, with a visible log and cancellation. Numerical cost is not bounded
by the free-space check: fine meshes and large air regions can require much
more memory and time. Start with the supplied mesh and refine deliberately.

The IPC action is in `plugin.json`; the source launcher uses the
originating KiCad API context and never selects another running editor.
The IPC Python must provide the desktop dependencies and `kicad-python`.
Source launch and IPC toolbar launch require separate validation; a live KiCad toolbar launch remains unqualified in the recorded evidence.

## Automatic dependencies and safe updates

First-open setup requires at least **3 GiB free** for candidate installation.
The manager discovers the latest non-yanked EMerge 3+ release on PyPI, installs
binary wheels into a new virtual environment, checks dependency consistency,
then performs four real coarse compatibility solves: line coupon, patch with
radiation, adaptive line and a synthetic polygon-region coupon. Only a passing candidate becomes active through
an atomic manifest update. The certificate binds installed EMerge's version to
the exact adapter and qualification code. These smoke checks cover the current
plugin workflows; they do not guarantee numerical accuracy, convergence or
every upstream capability.

Opening the tool checks for updates at most once per 24 hours. **Set up / check
updates** forces a check and retries failed setup. Existing working environments
are never upgraded in place. A failed update, network outage or unavailable
wheel leaves the active runtime selected. On first install, an incompatible
latest release falls back to the tested 3.0.0b9 baseline. **Restore previous
runtime** switches back to the retained compatible predecessor. Qualified
versions are retained for recovery, not silently deleted. Cancellation removes
only the current incomplete candidate and keeps its diagnostic log. Setup is
locked across windows so two first opens cannot race activation.

Managed environments live under the user's WayriCAD application-data directory
(`WayriCAD/quick-emerge/runtimes`). Set `WAYRICAD_QUICK_EMERGE_HOME` to choose
another drive, and `WAYRICAD_QUICK_EMERGE_PYTHON` to select a compatible base
interpreter. Setup logs and `active.json` are stored there. No administrator
installation is needed. The desktop/IPC host dependencies remain separate;
this manager provisions the EM solver and its dependencies.

## Visual workflow

### Simulate a PCB rule-area enclosure

1. Save the PCB with a closed Edge.Cuts outline, filled copper zones and an
   explicit two-layer stackup. Draw/name a polygonal **board rule area** around
   the subsection. Its XY enclosure is extruded through both copper layers;
   KiCad keepout permissions are not electromagnetic boundaries.
2. Select **Saved PCB rule-area region**, then **Load saved PCB rule areas**.
   Select the enclosure by name/UUID, its F.Cu signal and B.Cu reference nets,
   and review the entered relative permittivity and bare-copper approximation.
   Unsaved editor changes are excluded.
3. **Preview setup** shows clipped copper, holes and numbered ideal ports in
   the **PCB enclosure** and **3D setup** views. The inspector lists blockers.
   Read-only dimensions come from the crop and saved dielectric separation.
4. Run EMerge after reviewing the ports. Only clipped copper/substrate enters
   the solve, surrounded by the configured air margin. Board coordinates stay
   intact for field probes. One boundary port enables relative radiation
   extraction; multiple ports produce the full S-matrix and Touchstone.

![Saved-copper rule-area study and reviewed boundary ports](help-region.png)

Native polygon intersection with the actual board outline preserves concavity,
holes and disconnected portions. It never substitutes a bounding rectangle.
Tracks/arcs and SMT pads use a recorded 0.005 mm polygonization tolerance;
zones use saved fills. Natural board edges and existing board holes do not
automatically become ports: a feed must lie on an actual rule-area cut, with
reference copper covering the entire span.

The initial region solver supports **two-layer bare copper and 1–8 ideal
vertical lumped boundary ports**, homogeneous real εr and zero-thickness PEC.
Drilled pads/vias inside the enclosure, unsupported copper graphics, unfilled
intersecting zones, unselected cut conductors, curved rule-area contours,
ambiguous corner ports and incomplete reference spans block simulation.
Interior feeds, multilayer boards, footprint-local rule areas and populated
component models need further integration. No feed is invented when the
signal does not cross the enclosure. Validation is bounded to 20,000 total /
2,000 per-contour vertices; choose a smaller enclosure if exceeded. Multiple
dielectric slabs require review of the homogeneous material approximation.

Geometry, nets, source UUIDs, ports, source hash and region hash accompany each
run. Changes to source or reviewed geometry reject the run/result. Native
extraction uses installed KiCad Python separately from the desktop and solver;
set `WAYRICAD_QUICK_EMERGE_KICAD_PYTHON` if discovery fails. The PCB and adjacent
project files remain unchanged.

### Native viewports

Quick EMerge uses dedicated native wx scientific viewports with the same core
inspection controls as Quick PI/QuickTherm, extended for 3D field and radiation
samples:

- Each viewport has a compact **Orbit / Pan / Zoom / Probe** button strip,
  with **Fit, +, − and Image** beside it. In 3D, left drag performs the selected
  navigation action; **Probe** reserves left click for sample selection. Middle
  drag pans, and in Probe mode right drag orbits. Wheel zoom works throughout.
  In 2D, Pan drags the plot and Zoom draws a zoom rectangle. Shortcuts **O, P,
  Z, I** select Orbit, Pan, Zoom and Probe. The active button stays highlighted.

- Isometric, top, bottom, front and right presets; orthographic/perspective
  projection; wheel zoom; **Fit / F**; **1–4** camera shortcuts. Orbit, zoom
  and selected samples survive changes to colors and visibility.
- **True Z scale** keeps coordinate aspect ratios physical. Turning it off
  exaggerates Z by four for readability, explicitly labeled in the viewport.
  Neither mode changes solver geometry or samples.
- Separate substrate, copper, ports and field visibility; an optional **sample
  grid**, light/dark view backgrounds, and five color maps. The sample grid is
  not the FEM tetrahedral mesh.
- Shared linear/log field scales and optional manual limits in V/m across
  the 2D and 3D field views. Zero samples are masked on log scales; unknown
  samples remain missing. Radiation colors show normalized |E|, not height.
- Hover readouts and **Probe** click-to-select original samples; synchronized selection
  markers in the 2D/3D field views; a docked inspector; field min/max navigation;
  pinned field, network and angular radiation samples with CSV export.
- **Line cut** selects two field samples and plots 200 nearest-original-sample
  values against distance in mm. Gaps remain gaps; no interpolated measurement
  is invented. Export includes sample coordinates, distance, frequency and
  configuration/context hashes.
  Selecting Line cut enables Probe mode automatically in both field views.
- **Focus view / F11** expands the viewport and restores the setup/inspection
  panels afterward. Plot toolbars retain image export and navigation.

![Expanded native field viewport](help-viewport.png)

3D near-field picking chooses the closest projected original grid point within
14 pixels, not an arbitrary volume intersection. Field surfaces show cell-average
colors; large grids use at most 64 × 64 display cells for bounded rendering.
A reduced cell touching any unknown/masked original sample is omitted. Probes,
extrema, profiles and exports continue to use the full original sample grid.
The current near field remains a single recorded XY plane, not a volume slice
or a field recomputed when selecting another network frequency.

- Rotate the native 3D setup view and inspect patch insets, feed ports and
  substrate. The viewport reports physical aspect or explicit Z exaggeration.
- Inspect sampled S11 and, for the line coupon, S21. Click a frequency sample
  or Smith-chart point for return loss, VSWR and complex input impedance.
- Select a CPU/GPU backend (its optional dependencies must be present), linear
  or adaptive AAA frequency sampling, and optional adaptive mesh passes. For
  adaptive sweeps, points is the total sample budget, with a minimum of five.
  Inspect solver warnings: reaching a sample/mesh limit is not convergence.
- Probe the nearest near-field sample on the XY plane. The plane is sampled
  at the middle **solved** frequency; it does not track a clicked S-parameter
  frequency. Blank samples mean unknown/outside mesh, never zero field.
- Overlay that electric-field plane on the template in the native 3D field view.
- Inspect a rotatable 3D relative far-field electric-field pattern for the
  patch. Its radius is normalized; it is not gain, efficiency or distance.
- Use plot toolbars to pan, zoom and export images. Save/load setup JSON for
  another run. Editing setup clears the old plots and requires another preview.

Each run has its own directory, containing `request.json`, `status.json`,
`solver.log` and, only after successful computation, `result.json`. Completed
results include configuration, source path/hash, backend version, sampled
complex S-parameters, fields and assumptions. Source/config changes reject
publication or collection. Source PCB files are never written. Cancelled and
failed runs retain diagnostics; they are not presented as completed results.
Completed runs also contain `network.s1p` or `network.s2p` with the full solved
S-matrix, explicit reference impedance and real/imaginary values in Hz.
Setup JSON and completed runs are user artifacts, not disposable caches.

## Numerical scope

Conductors are zero-thickness PEC surfaces. The substrate is homogeneous,
lossless and nondispersive. The outer air box uses a first-order absorbing
boundary. Ports are vertical lumped sheets with an explicit reference
impedance. There is no conductor loss, dielectric loss, component model,
automatic mesh-convergence acceptance or measured validation yet. Adaptive mesh
and sweep controls are available; their stopping limits can precede convergence.
The minimum plotted S11 is only the minimum **sampled** value. No vector-fit
interpolation is substituted for solved data. VSWR is undefined for
reflection magnitude greater than or equal to one. Singular impedance and
unknown field samples stay unknown.

The adapter follows the APIs in upstream EMerge 3.0.0b9's
`examples/demo4_patch_antenna.py` and `examples/demo6_striplines_with_vias.py`.
Geometry is newly implemented against those APIs; no EMerge solver code or
runtime is vendored. EMerge is by Robert Fennis and contributors, distributed
under GPL-2.0-or-later; see [upstream](https://github.com/FennisRobert/EMerge).

## Next implementation milestones

1. Qualify the pinned adapter with real solves: analytical line references,
   patch frequency/mesh refinement and air-boundary sensitivity; compare field
   and radiation exports against EMerge's own displays.
2. Extend the implemented rule-area extraction beyond two-layer bare copper:
   via barrels/plating, multilayer material stacks, populated models and
   interior ports, preserving the reviewed polygon/source/port contracts.
3. Add graphical signal/reference port selection on extracted geometry,
   multiple excitations, frequency-selectable fields, vector/phase displays,
   volume probes, radiation cuts and gain/efficiency with normalization.
4. Qualify independent installation, originating-editor toolbar launch, theme
   behavior, cancellation and convergence workflows across supported systems.

## Validation

```powershell
python -m pytest quick_emerge_plugin/tests -q
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m unittest discover -s quick_emerge_plugin/tests -p test_pcb_regions.py -v
python -m quick_emerge_plugin --check-runtime
```

Development validation on Windows with Python 3.14, wxPython 4.2.5 and installed
KiCad CLI 10.0.6 covers configuration, analytical reflection metrics, adapter
unit contracts and subprocess lifecycle. Real EMerge 3.0.0b9/SuperLU runs under
Python 3.11.9 completed for a three-frequency line coupon, a three-frequency
patch with radiation extraction, and a five-sample adaptive coupon. The latter
intentionally exhausted one refinement pass and the sample budget; neither is
convergence acceptance. A real clipped saved-copper region completed both through
the scripted service and native UI. Optional solvers, general populated/multilayer PCB extraction and a live
KiCad toolbar launch remain unqualified. See [validation evidence](VALIDATION.md).
EMerge 3.0.0b9 itself requires Python older than 3.14; select a compatible
separate solver interpreter.
