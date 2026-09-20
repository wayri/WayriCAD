# Magnetic core analysis and its limits

The winding view remains the first stage: choose a geometry, review copper and
terminals, then apply. **Core tools** provides optional analysis without adding
another bank of controls to the winding form.

1. **Edit custom core** accepts effective magnetic cross section Ae (mm²),
   effective core path le (mm), total series gap (mm), relative permeability and
   a saturation threshold (T). These are magnetic dimensions, not bounding-box
   dimensions. Editing a canned core clears its unverified loss coefficient.
2. Optionally paste measured **B-H samples** as `B,H`, in T and A/m. Begin with
   `0,0`; both quantities must increase. The table must cover the threshold.
   Export/import the JSON core catalogue to preserve these inputs.
3. **Current / saturation sweep** draws flux density, incremental inductance or
   ideal gap force against current. It provides the numerical samples and CSV.
   Invalid input clears the previous plot. Above the specified threshold a linear
   permeability model has no valid force/inductance result; no artificial flux
   clamp makes it appear safe. A tabulated curve may continue beyond the threshold
   within its measured range, with the threshold still highlighted.
4. **Transformer pulse** checks one-pulse flux change from volts and on-time.
   Add initial/reset flux yourself; the calculation does not establish reset,
   flyback/forward topology validity or operating temperature.
5. **Inspect STEP core** imports closed solids in an isolated FreeCAD process,
   displays an isometric surface wireframe and reports actual solid volume and
   outside dimensions. It does not infer Ae, le, gap or a material from the CAD
   bounding box. Enter those explicitly in the core editor.

![Native current sweep using explicitly synthetic material samples](help-core-sweep.png)

This image demonstrates a synthetic B-H knee, not a characterized commercial core.

## Equations and assumptions

The static circuit solves `N I = H(B) le + B gap / μ0`, using monotone piecewise
linear H(B). Each interval is inverted analytically, without iteration or
extrapolation. Differential inductance at the selected current is
`N² Ae / (le dH/dB + gap/μ0)`. Negative current reverses signed B and flux.
The main winding analysis uses this differential inductance for custom/cored
models; air-core winding inductance retains its planar geometry approximation.

The force estimate `B² Ae / (2 μ0)` assumes one uniform pole face closing one
gap. It is unavailable at zero gap or when a linear material model is outside
its valid saturation range. It is not an arbitrary actuator Maxwell-stress
integration. Transformer pulse flux swing is `V ton / (N Ae)`.

No result here includes fringing, leakage field maps, hysteresis, temperature
dependence or eddy-current loss distribution. B-H samples characterize an
anhysteretic static relation, not loss. A zero custom loss coefficient means
**loss has not been characterized**, not a lossless real core. Existing catalogue
loss coefficients remain screening assumptions. Nonlinear B-H cores are refused
by the older coupled-motion integrator instead of silently reverting to constant
permeability. Use the static sweep for those cores.

## STEP runtime

FreeCAD is optional; winding and circuit tools run without it. Windows discovers
FreeCAD's bundled Python under Program Files or the user's Programs directory.
On any platform set `WAYRICAD_MAGNETICS_FREECAD_PYTHON` to a Python executable
that imports `FreeCAD` and `Part`. `WAYRICAD_MECHANICAL_FREECAD_PYTHON` is also
accepted. The process receives explicit paths, has a private temporary directory
and a 90-second timeout. STEP input is bounded to 100 MiB and preview tessellation
to 200,000 entities. No CAD macro is executed. Closing the preview does not change
the source STEP or PCB; an in-flight worker finishes or reaches its timeout.

## Full-field solver integration status

The inspected SPIKES source includes linear/nonlinear H(curl) magnetostatics,
planar and axisymmetric reference solvers, inductance and force extraction, and
monotone B-H materials. These are C++ mesh-level interfaces, not a ready STEP
reader or a packaged Python solver API. They are **not linked into this plugin**.

An integration still needs a portable C++20 worker build, qualified volume or
meridian meshing, region/material assignment, winding current excitation,
external-boundary treatment, convergence studies, force-surface selection and
result transfer to the native preview. STEP inspection is geometry preparation,
not that field solve. Arbitrary STEP transformer/actuator FEA remains unimplemented. A separate limited
axisymmetric linear field solver is now provided below; it is not the SPIKES C++
backend and the circuit tools must not be described as FEA.


## Axisymmetric field: a real, bounded FEM subset

**Core tools → Axisymmetric field** opens a separate two-stage native workflow:
**Geometry** defines an annular winding, and **Field and mesh** displays the solved
field. The geometry is explicit and independent of both the PCB winding and STEP
reference. A bore cylinder or annular linear core is optional; advanced core,
mesh and air-boundary settings start collapsed.

The local solver uses first-order triangular azimuthal vector potential Aφ on
an axisymmetric meridian mesh. It integrates the cylindrical curl energy with
three-point triangle quadrature: `Br = -∂z Aφ`, `Bz = ∂r Aφ + Aφ/r`. The sparse
linear system uses NumPy/SciPy in the private plugin runtime. Coil region edges
align with the grid, preserving the entered ampere-turns. Axis and finite outer
air edges impose Aφ=0. The reported L is `2 magnetic energy / I²`; source-work
balance and linear residual are checked before returning results.

The native view offers |B|, signed Br, signed Bz and optional triangle edges.
It mirrors the solved r≥0 meridian to show the physical axial section. Click a
cell to inspect its field components and region. The JSON export includes mesh,
cell fields, source ampere-turns, energy, inductance, residual and the exact inputs.

**Review convergence** runs the base mesh, twice the radial/axial cell counts,
and a 25% larger air domain with approximately preserved mesh spacing. It reports
changes in inductance and center-axis B. An air winding also compares refined
center-axis B against the finite-solenoid analytical solution integrated across
the winding's radial thickness. This is convergence evidence, not automatic
accuracy certification. Increase the domain and refine until changes meet the
application's tolerance; high-permeability materials need particular care.

![Actual native axisymmetric field and mesh](help-axisymmetric.png)

The default 100-turn, 8–10 mm radius, 30 mm tall, 1 A air winding has a 4,488-triangle
base mesh. Validation measured 72.6347 µH and 3.45389 mT at the axis center; the
analytical finite-air-winding reference is 3.59145 mT. Doubling mesh density
changed L by 0.54%; enlarging the finite air domain changed L by 2.26%. The
refined axis-field error was 3.95%. Those differences demonstrate why one solve
is insufficient; they are not hidden in an accuracy claim.

This subset excludes nonlinear B-H FEM, saturation feedback, eddy currents,
hysteresis, multiwinding transformer excitation, arbitrary non-axisymmetric
planar windings, STEP volume meshing and Maxwell-stress force extraction.
Core B is displayed so the designer can compare against the material threshold;
constant permeability does not automatically saturate. Force remains the
separately labeled magnetic-circuit estimate.


### Reproducible field CLI

Create a UTF-8 JSON object containing any `AxisymmetricSpec` fields (an empty
object uses the documented default air winding), then run in the prepared Python
runtime:

```text
python -m planar_magnetics_plugin.axisymmetric --input winding.json --output field.json --convergence
```

Dimensions are millimeters; current is amperes. The output file contains the mesh
and cell fields while stdout returns a short JSON summary. Invalid input returns
exit code 2. The input file is never overwritten by this command.
