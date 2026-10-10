# QuickTherm STEP component heating

## Implemented model

An explicit storage node receives each component's dissipated watts once. Reviewed capacity is J/K; reviewed contact resistance is K/W. Weighted saved-pad contacts, footprint-bound proxies or declared virtual sinks connect that node to the thermal graph. Optional exposed area, convection and emissivity describe package-to-ambient rejection; nothing is inferred from STEP material names. Body nodes leave junction temperature and junction limits unknown. A junction RC is an equivalent node, not an internal-solid temperature field.

Source-bound Quick PI imports transfer planar and barrel I²R heat separately into copper nodes. Exact polygon/copper/board contact area and retained resolved annulus stencils conserve watts. Via segments deposit half power at each end under a uniform axial assumption. Unsupported voids, missing lands, coarse unresolved contacts and infeasible electrical operating points reject the transfer. Imported conductor losses remain fixed unless explicitly scheduled; this import does not re-solve electrical currents during thermal playback. Quick PI's electrothermal studies remain the feedback workflow.

KiCad CLI owns STEP placement, scale, rotation and offsets. A private snapshot tags STEP PRODUCT identities without altering source geometry. FreeCAD reads leaf solids and produces bounded display meshes. KiCad XY is restored by reversing STEP Y; STEP Z and saved surface offsets remain unchanged. Native rendering sorts board and component faces together to avoid hiding packages behind a whole-board collection. Models with missing geometry retain explicit coverage gaps. No source model, PCB or library is written.

## Acceptance evidence

- Windows, KiCad 10.0.6, native Python 3.11.5, wx 4.2.2, FreeCAD 1.1 Python 3.11.14.
- 78 focused native regressions passed: analytical single RC, coupled capacity matrix exponential, timestep refinement, energy conservation, schedule-step continuity, initial temperatures, body/junction distinction, parallel air cooling, vacuum radiation, planar mapping and barrel allocation/rejection. Service checks include copper-only heat, air/forced-air virtual sinks and actual contact temperature rise after a surface cooling split.
- Complete portable QuickTherm suite: Python 3.14.2, 217 passed, 22 native/optional skips and 179 subtests passed. Tests cover table parsing, source/stackup/energy mismatch, body-frame limits, model path resolution and unchanged solver contracts. Native/optional skips remain separate from passes.
- `tools/check_component_thermal.py` loads the public demo, explicit assumed stackup and two validation STEP boxes. It checks rotated XY extents and top/bottom Z placement while also loading real capacitor/connector library solids. A 41-frame study heats and cools the component nodes; maximum interval energy residual was below 5e-14 W. Source PCB and STEP hashes remain unchanged. Native 3D and self-contained HTML/JSON exports include real meshes and storage states. Synthetic inputs are workflow evidence, not measured hardware temperatures.
- A converged coupled PI reference imported all 16 conductor sources, conserving 0.006157142857142859 W. Missing field thickness comes only from consistent explicit electrical mesh thickness; layers without such evidence reject the transfer.
- The extracted standalone PCM exercises the real subprocess solver and STEP loader, native modal table rejection/editing, 3D geometry, scrubbing, exports and source/model immutability. Runtime discovery is pinned to the installed KiCad executable; checkout paths are removed from plugin imports. Final package/wheel validation is recorded during release preparation. Report JavaScript is checked syntactically; browser rendering is not claimed as a native GUI test.

## Reproduction and screenshot provenance

[Native component heating](../../quick_therm_plugin/examples/quicktherm-component-heating.png) is an unmodified native capture using the public demo and disposable validation geometry. No personal paths, user designs or private network addresses appear. C1 is a rotated top-side 4×2×3 mm box with body R=10 K/W, C=0.2 J/K and 1 W until 4 s, then zero. C2 is a bottom-side box with junction-equivalent R=5 K/W, C=0.1 J/K and 0.5 W. C3/J1 retain actual KiCad library models and unknown temperatures. Initial/ambient is 20 °C; duration 10 s, step 0.25 s; grid long axis 24; assumed copper/core/copper thickness 0.035/1.53/0.035 mm, conductivity 385/0.3 W/(m·K), emissivity 0.85, airflow 0 and volumetric capacity 3.45/1.8 MJ/(m³·K). No package surface cooling is declared in this fixture. Final C1 body is 34.55168 °C and C2 equivalent junction is 50.87156 °C; maximum interval energy residual is 4.70e-14 W.

Run `python tools/check_component_thermal.py` with native dependencies. Use `--plugin-root` for an independently extracted PCM `plugins` folder. The helper confirms exact rotated XY extents and KiCad-exported surface offsets (top base 1.615 mm, bottom top -0.085 mm), instead of adding guessed height offsets. It never changes the source demo or model files during analysis.

## Limits

One temperature per declared part; no internal die/package gradient, surface view-factor radiation, CFD or inferred thermal properties. Footprint-bound contact proxies and finite-volume mesh approximation can affect local peaks. STEP mesh deflection and triangle limits affect display detail only. Native compatibility on other OS/KiCad versions needs separate verification.
