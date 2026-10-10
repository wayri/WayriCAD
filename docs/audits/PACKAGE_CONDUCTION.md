# Package contact conduction acceptance

Scope: explicit lead/solder/BGA paths in Quick PI 2.5D constant-current DC and
QuickTherm multilayer steady/transient studies. This implementation is included in the 3.6.14 release candidate. The private
pre-release 3.6.13 test archives described below were never published.
See [inputs, equations and limits](../PACKAGE_CONDUCTION.md).

Validation recorded on 2026-10-10.

## Automated checks

| Suite | Result |
| --- | --- |
| Shared/root, portable Python 3.14 | 407 passed, 73 skipped; 164 subtests passed |
| QuickTherm, portable Python 3.14 | 226 passed, 23 skipped; 190 subtests passed |
| Quick PI, native KiCad Python 3.11 | 256 passed; 186 subtests passed |
| Native expanded-sidebar bounds | 1 passed, three window sizes |
| Native component workspace, whole-board actions and sidebar | 6 passed |

Suites run separately, matching their import contexts. Portable skips include
native GUI/KiCad requirements and are not passes. The portable PI run encountered
missing VTK; the final native full suite above supplies VTK and passed. The native
pytest run appends the portable pure-Python pytest installation after the KiCad
libraries and disables automatic third-party pytest plugins.

Commands: `python -m pytest tests -q`,
`python -m pytest quick_therm_plugin/tests -q`,
`pytest.main(['quick_pi_plugin/tests', '-q'])` in native Python, and
`python -m unittest quick_therm_plugin.tests.test_sidebar_layout` in native Python.
The six native UI checks also cover edited/scanned inputs, asynchronous worker
execution, retained views/probes, stale result invalidation and ordinary close.
The whole-board check expects automatic 3D selection when real STEP models load;
it verifies a 3D axis in that case and the top board field otherwise.

## Reference checks

- Cylinder and rectangular resistances match `rho × length / area` and
  `length / (k × area)`, with explicit mm-to-m conversions.
- Truncated-sphere resistance agrees with independent 100,000-interval midpoint
  quadrature to relative tolerance `1e-9`.
- Parallel contacts solve unequal current and heat sharing. PI analytical
  fixtures check nodal residuals, package voltage drop, source/sink limits and
  separate sheet/barrel/contact losses. Single-face attachment retains finite
  plated barrel resistance.
- Thermal contacts reproduce parallel resistance and conductance-weighted
  package temperature between unequal pad temperatures, including reversed heat
  flow at zero component dissipation. Source peaks cover every contacted pad.
- A component/contact RC transient agrees with its analytical exponential
  response within `0.001 °C` at a `0.002 s` time step.
- Joint heat allocation matches series thermal-resistance midpoint coordinates;
  unequal lead/solder segments do not receive an arbitrary equal endpoint split.
  Steady and transient conservation checks include joint heat once.
- Missing, ambiguous, duplicate, cross-net electrical, oversized-neck and
  double-counted contacts reject. Unknown currents and thermal properties remain
  unknown. Unsupported solver modes reject before board loading.

## Native workflow

`tools/check_package_conduction.py` generates a public fixture, runs the actual
saved-board PI mesher/solver, exports HTML/JSON, imports the disk JSON into
QuickTherm, and runs steady plus spatial transient heating. It checks source
hashes, pad UUIDs, explicit layer depths, segment properties and I²R consistency.
It also opens both full native windows and their actual modal contact editors,
rejects a nonfinite material value, corrects it and verifies accepted data.
The PCB's SHA-256 remains unchanged. No running PCB Editor IPC session is used.

Windows / KiCad 10.0.6 / native Python 3.11.5 / wxPython 4.2.2:

| Generated workflow result | Value |
| --- | --- |
| Copper heat | `0.0374354285714 W` |
| Lead/solder heat | `0.00715176892668 W` |
| Entered component heat | `0.3 W` |
| Thermal input total | `0.344587197498 W` |
| PI relative energy residual | `< 3e-14` |
| Steady thermal residual magnitude | `< 4e-15 W` |
| Maximum transient energy residual magnitude | `< 4e-14 W` |
| Transient frames | `21`, through `1 s` |

The same exported-report transfer passed from extracted independent PCM ZIPs
with source-plugin paths removed. Both ZIPs contain byte-identical shared
contact model/editor files. The isolated workflow is numerical/report acceptance;
native editor checks use source windows. These private test archives retain the
source metadata version and must not replace published 3.6.13 packages.
The final private Quick PI ZIP has SHA-256
`0eb44ea47fd9e6691a86afb927ef20fb458e334c5daec17bfb41fbe2bf5776a1`;
the final QuickTherm ZIP, including sidebar sizing and offline help, has SHA-256
`992929b86102b5860bab02656e055a5bb78be5ab6ea37670452d846be1d638b4`.

The native saved-pad test also binds two distinct C1 pad faces and solves a
transient study without modifying its saved board. Enabled copper-layer IDs
come from KiCad; this runtime uses F.Cu=0 and B.Cu=2.

## Sidebar clipping correction

The board-model heading occupied the first column of a two-column grid, making
the scrollable content wider than the visible sidebar. The previous compaction
also enlarged explicit 50 px All/None buttons to 90 px. Headings now span their
own row, expanding inputs use available width, and explicitly sized buttons and
standalone numeric fields retain their sizes. Sidebar width uses DIP units.

`quick_therm_plugin/tests/test_sidebar_layout.py` checks expanded sections and
long field names at 940 × 680, 1000 × 740 and 1440 × 900 window sizes. It asserts
that the virtual width and every displayed input/button fit within the visible
sidebar, and that controls retain usable width. The native check passed.

## Limits

The native fixture is a regression case with illustrative properties, not a
qualified solder alloy, component model, board mesh or hardware measurement.
Real studies still require reviewed materials/boundaries and spatial/time
refinement. Contact paths are constant-property, massless axial elements;
internal package gradients, detailed pad spreading, joint heat storage and
temperature-dependent electrical feedback are not implemented. STEP geometry
does not infer material or connectivity. Native testing here does not establish
other OS/KiCad versions, dark-theme operation, PCM installation or live IPC.
