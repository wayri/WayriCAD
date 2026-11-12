# Primary winding thermal study

Open **Design > More > Primary winding thermal study** after entering the winding.
The dialog analyzes the current form, not an old winding preview. It is read-only
and does not place copper or modify a PCB. Its rectangular coupon is a declared
study geometry, **not an extraction of the open board**. The winding is centred
on that coupon and mapped to successive physical copper layers.

## Material and boundary forms

Enter coupon width/height, physical copper-layer count, uniform copper-midplane
spacing, dielectric and copper thermal conductivity (W/m/K), and grid resolution
(24-80 long-axis cells). Copper thickness comes from the winding form. At least
two thermal layers are required, even for one winding layer. Other copper planes,
components, vias and fixtures are not automatically added. Values initially shown
are editable screening assumptions, not measured laminate properties.

Set ambient temperature, face convection coefficient and board emissivity.
Heat leaves the top/bottom faces; edge cooling, airflow CFD, transient thermal
capacity and package/core shading are not solved. The advanced Python/JSON API
accepts the shared kernel's explicit stackup/outline/copper/barrel/mount geometry
and boundary settings instead of a rectangular profile. Coordinates are mm;
thermal conductivities are W/m/K and heat is W. No sibling plugin is imported.

Choose constant RMS **current** or constant **voltage** and an explicit copper
reference temperature/coefficient. Voltage drive is a purely resistive DC
equivalent; it does not solve inductance, PWM, back EMF, transformer load or AC
impedance. DC uses trace resistance only. Optional `legacy_ac` in current mode
freezes the existing first-order skin/proximity multiplier: it is not a
temperature-dependent electromagnetic loss extraction.

## Coupling contract

Each primary centreline segment becomes a finite-width rectangular heat support
on its declared physical layer. Segment reference resistance is
`rho * length / (width * thickness)`, with `rho = 1.724e-8 ohm m` at the chosen
reference temperature. Current-mode loss is `I^2 R(T)` and voltage-mode current
is `V / sum(R(T))`, where `R(T) = Rref [1 + alpha (T - Tref)]` uses the local
source-area-weighted temperature. Parallel layers use equal current sharing
(`Rref/layers^2` contributions); redistribution between unevenly heated parallel
branches is **not** solved. The effective parallel result is a screening
assumption, not an electrical-network solution.

The bundled `wayricad_runtime.thermal_multilayer` QuickTherm kernel maps source
area overlap conservatively and solves layer-resolved steady-state heat flow.
The wrapper damps local temperature updates by 0.5 and requires every segment
temperature change below 0.01 C by default (60 iterations). Nonconvergence,
nonpositive resistance, invalid geometry and temperatures above the selected
validity ceiling fail the study instead of returning an accepted result.

Trace polygons are sampled for lateral copper conduction. Segment corners and
subcell copper continuity are approximate; inspect 24/48/80-cell sensitivity for
your geometry. Heat conservation does not validate thermal contact, material or
magnetic physics. No qualified 3D magnetics, eddy-current, core-temperature or
distributed magnetic-loss solve is claimed.

**Excluded heat:** pads, terminals and via Joule heating, secondary winding loads,
dielectric losses, and automatically inferred core heat. Primary trace loss can
therefore differ from the older winding estimate, which includes a nominal via
length. Secondary windings are rejected rather than silently underheated.

## Optional core contact

Core magnetic loss remains a separate estimate (unknown if its coefficient is
zero). To include core heating, explicitly enable a contact and enter the watts
actually entering the board, its rectangular area/position and physical layer.
The API accepts `core_contact = {power_w, layer_id, polygon_mm}`. This is a
prescribed board heat input with no inferred temperature drop/contact resistance,
not a model of the core itself. It neither assumes all estimated core loss enters
the PCB nor invents core conductivity, density, heat capacity, contact resistance,
or temperature-dependent permeability/loss from a core material name.

## Results and CLI

Review each layer's temperature map, trace loss, resistance-weighted winding mean,
maximum cell temperature on winding support, operating current/resistance and
heat-balance residual. The JSON also records the maximum segment-average
temperature separately; cell and segment maxima are not subcell hot-spot bounds.
The JSON also
contains all declared inputs, local source temperatures/support weights,
iteration history, assumptions and a fingerprint. Editing any thermal form clears
the map and export eligibility. A fingerprint mismatch rejects stale export.
Exports are non-overwriting; choose a fresh destination.

The native dialog runs one background worker at a time. Inputs are deep-copied on
the GUI thread; the worker never reads controls or board objects. **Cancel**,
input edits and dialog destruction request cancellation. The shared backend's
cancellation hooks are used where available; older backends are checked before
and after calls and between outer iterations. An active sparse linear solve
cannot be interrupted. Until it returns, another solve cannot start; late or
stale output is discarded and never re-enables export. Completion is dispatched
only to an active dialog, with another active/input check before displaying it.

From the suite source checkout (or installed Python package with bundled runtime):

```text
python -m planar_magnetics_plugin.thermal_coupling planar_magnetics_plugin/thermal_example.json --output thermal-study.json
```

The [example input](thermal_example.json) declares a two-layer coupon and primary
current drive. Edit its assumptions for your material and environment. JSON
requires `coil`, either `profile` or `geometry`, `settings`, `drive`, and
`layer_map`; `origin_mm` and `core_contact` are optional. The example's values are
not a qualified material preset. Running this dedicated module does not require
changing the suite CLI or installing another plugin.

## Verification boundary

[Focused tests](tests/test_thermal_coupling.py) compare a uniform full-face source
with the analytical two-face convection/through-thickness conductance network,
and current/voltage temperature feedback with closed-form fixed points. They
check heat conservation, explicit core contact, stale results, outside/cutout
geometry, invalid mappings, convergence failure, generated winding transfer and
non-overwriting CLI output. These are numerical/model-contract checks, not
measurement or native-editor qualification.
