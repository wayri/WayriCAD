# KiWay Trace RLC / Impedance Analyzer

Measures routed PCB geometry between selected pads and produces first-order
resistance, capacitance, inductance, and characteristic-impedance estimates.

## Inputs and cross-navigation

- Live selected pad/track net and endpoint synchronization.
- Start/end pads, frequency, optional differential mate, and explicit reference
  copper layer.
- All stackup rows parsed from KiCad metadata or the board file when the SWIG
  stackup object is opaque.
- Route selection back into PCB Editor after analysis.

## Model

Resistance uses `R = rho*l/(w*t)` with copper resistivity and measured track
width/thickness. The current capacitance and inductance approximation uses
`C' = epsilon0*Er*w/h`, `L' = mu0*h/w`, and `Z0 = sqrt(L'/C')`, where `h` is the
dielectric separation from each routed layer to the selected reference layer.
The report records the exact reference layer, `h`, `Er`, copper thickness, and
stackup source used.

## Limitations

This is not a 2D/3D field solver. The approximation omits solder mask, trapezoidal
etch, copper roughness, dispersion, frequency-dependent dielectric loss, complete
via-barrel/parasitic models, plane splits, nearby copper, and connector/package
discontinuities. Aggregate-net fallback is explicitly reported when no connected
start/end path can be resolved. Validate critical interfaces with a field solver,
SI simulation, TDR, or measurement.
