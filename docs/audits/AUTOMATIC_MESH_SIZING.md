# Automatic mesh sizing

Automatic sizing supplies a geometry-based starting mesh and local size targets.
It does not estimate solution error, establish convergence or qualify physical
hotspots. Manual sizing remains available. UI and command-line studies use the
same recorded settings and retain source-hash checks.

## Methods and scope

| Model | Automatic sizing | Limits |
|---|---|---|
| PI layered DC | Background edge from occupied copper extent and a triangle-budget estimate; smaller targets near saved straight tracks, pad contacts and supported via lands. A graded size field drives conforming shared-edge midpoint refinement. | Native contours and holes remain fixed. Curved-track width targets, arbitrary zone necks and error-driven remeshing remain unresolved. The exact triangle guard can reject a recommendation; local targets are not silently coarsened to force a solve. |
| Thermal layered finite volume | Board/source dimensions recommend a base grid. Rectilinear intervals split near sources, explicit contacts, barrels and material-region bounds. Sources and contacts take priority when the total layer-cell budget is tight. | Tensor-product splits extend across the grid. Bounded feature selection, pass limits and node budgets can leave fine features unresolved; those omissions are reported. Thin annuli and narrow rotated copper are not automatically resolved by a bounding-box target. |
| Thermal thin sheet | Automatic base-grid recommendation. | Uniform grid only; local adaptive refinement belongs to the layered model. |
| PI volumetric FEM / thermal CalculiX | Manual sizing. | Automatic spatial sizing is not implemented for these backend contracts. |

PI refinement studies fix the automatic recommendation once and then compare a
family of uniformly refined manual meshes. Thermal refinement studies retain
their requested base-grid sequence and scale local targets with it; identical
actual grids cannot satisfy the mesh gate. Spatial refinement and thermal
time-step refinement remain separate checks.

## Regression and packaging checks

- 80 native-runtime numerical, meshing, convergence and CLI tests passed.
  These include analytical strip resistance, uniform layered heat flow,
  conservation, shared-edge conformity, budget limits, cancellation and
  distinct refinement grids.
- The PI automatic/manual/3D-control test and its associated sizing suite
  passed 11 tests and exited cleanly using the normal frame-close path.
  The thermal native workflow verified automatic/manual controls, request
  settings, result summaries and stale-result invalidation with STEP loading
  disabled for the focused check.
- The portable focused suite passed 26 tests and skipped two VTK-dependent
  checks; those checks passed in the native runtime. The broader root suite
  passed 494 tests with 88 skips.
- Built and validated 23 disposable PCM packages. Independent extracted PI
  and thermal packages generated actual automatic meshes using only their
  own bundled modules. Documentation source validation and whitespace checks
  passed. Candidate binaries were not published over existing versions.

The implementation uses established mesh-sizing ideas, but its thresholds and
budgets are WayriCAD heuristics, not literature accuracy bounds. See
[Gmsh mesh-size controls](https://gmsh.info/doc/texinfo/gmsh.html#Specifying-mesh-element-sizes)
for mesh-generation background and
[NASA's spatial-convergence guidance](https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html)
for the distinction between selecting a grid and assessing its error. The PI
local subdivision is implemented in WayriCAD; it is not a Gmsh field solver.

## Saved Marble checks

Windows, installed KiCad 10.0 Python/native geometry, NumPy 2.4.2 and the
available SciPy/VTK/Gmsh runtime were used. The board revision and assumed
operating points are those in the [Marble analysis](MARBLE_COUPLED_ANALYSIS.md).
Source PCB bytes remained unchanged.

- A selected 1.2 V path with a 0.2 A load used 13,384 vertices and 23,511
  automatically sized triangles. It reported 1.1884286745 V at the load and
  0.0023142651 W modeled loss. Current-balance error was approximately
  9.8 × 10⁻¹³ A and relative power-balance error 2.75 × 10⁻¹². These are
  conservation checks, not a mesh-convergence or measured-board accuracy claim.
- The 12-layer thermal sizing review stayed within its 50,000 layer-cell
  budget: 70 × 59 × 12 = 49,560 rectangular layer cells before outline masking.
  Retained heat-source regions met their heuristic size targets. Fine barrel
  and material features remained unresolved or outside the bounded feature
  selection; those warnings must be reviewed. This was a sizing/extraction
  check, not a new complete-board temperature solve.

See the [PI instructions](../../quick_pi_plugin/README.md) and
[QuickTherm instructions](../../quick_therm_plugin/README.md) for controls,
request keys and command-line examples. No candidate binary replaces an
already published release asset.
