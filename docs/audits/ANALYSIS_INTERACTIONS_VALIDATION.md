# Interactive analysis and spatial thermal validation

Validated on Windows using KiCad 10.0.6 native Python and its NumPy/SciPy/wx/VTK runtime. This records development-source checks, not universal GUI or physical qualification.

## Saved-board runs

The public Marble board was read without modification (SHA256 `3304ba37c2bd891849fc36b500cd940934aaf1f2013a95639c03564fb925c512`). It has 12 copper layers, 3,664 vias, 127 zones and seven plated slots. Four illustrative sources total 8.3 W. Conductivities, plating and boundary coefficients were explicit assumptions; the 24-cell long-axis grid was not independently mesh-converged.

| Equivalent boundary | Steady balance residual W | Outcome |
|---|---:|---|
| Air, h = 9 W/m²K, emissivity 0.8 | -1.20e-11 | Numerically converged |
| Vacuum, zero convection, emissivity 0.8 | -1.56e-11 | Numerically converged |
| Forced air, h = 40 W/m²K | -8.66e-12 | Numerically converged |
| Potting, k = 1 W/mK, thickness 1 mm, outer h = 10 W/m²K | -1.24e-11 | Numerically converged |
| Sealed, enclosure 30 °C, h = 8 W/m²K | -1.34e-11 | Numerically converged |

The air spatial transient ran 10 seconds with a 1-second step and explicit copper/dielectric volumetric heat capacities. U1's power multiplier decreases from 1 to 0 between 3 and 4 seconds. Eleven stored frames were generated; maximum step energy residual was below 6e-12 W. The final native frame test verifies U1's displayed power is zero. Complete saved-board analysis took about 59 seconds, including geometry extraction and the steady initialization; this is not a benchmark against another simulator.

## Interaction checks

- Native Quick PI, Quick SI and QuickTherm windows constructed successfully. Programmatic native events selected a saved-board copper net, pinned/reset a coordinate probe and changed thermal frames. The real saved-board report and 3D figure rendered successfully.
- Thermal frame tests cover weighted contacts, scheduled junction offsets, absent resistance, temperature limits and immutable source results. Three camera orientations recover the same board point.
- Mechanical tests execute the report JavaScript triangle picker with Node, including nearest hits and section clipping. Native picking uses the same clipping predicate.
- Heater/magnetics tests retain drawing and sensor rendering and test exact cell/sample probes. Coordinate probes do not imply solved electromagnetic fields.
- Analytical transient tests cover RC heating/cooling, adiabatic storage, two-node conservation, radiation and time-step refinement.
- All 19 disposable PCM archives validate against the official schemas, standalone shared-runtime layout, actions, icons and syntax. Candidate archives were generated separately from the public release feed.

Physical mouse workflows for every native/browser viewport were not run. Potting storage, enclosure heating, CFD, package die/barrel-metal storage and coupled circuit feedback are not covered. The thermal 3D overview is board geometry with temperature fields and illustrative markers, not a STEP component assembly. Stable stepping and small conservation residuals do not establish material, mesh or physical accuracy.
