# Motor winding and electromechanical models

This workbench supports winding-layout and sinusoidal-machine calculations. It keeps coil assignment, phase balance, flux assumptions, electrical position and mechanical units visible. These calculations are independent of the separate axisymmetric transformer-field model.

## Research reviewed

Research review date: 20 September 2026. Recent publications guide the model boundaries and checks; they are not blanket validation of this implementation.

| Primary source | Use in this workbench |
|---|---|
| [Taghavi Araghi et al., IET Electric Power Applications, 8 March 2025, DOI 10.1049/elp2.70002](https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/elp2.70002) | Section 4.1's conventional phasor-sum winding-factor method supplies a reproducible baseline. The published 12-slot/10-pole conventional winding factor is approximately 0.933. The paper's optimized shifted-slot and PM-assisted reluctance geometries are not implemented. |
| [Forbes et al., Journal of Magnetism and Magnetic Materials, 2025, DOI 10.1016/j.jmmm.2025.173416](https://digital.library.adelaide.edu.au/items/2ba50799-ff2b-468a-8909-687c2a54010b) | The published elemental-model research includes nonperiodic geometry, magnetic materials and end effects. These capabilities establish useful targets beyond the present periodic sinusoidal baseline; its solver has not been reproduced here. |
| [Vatani et al., IEEE Transactions on Industry Applications, DOI 10.1109/TIA.2026.3694046](https://scholars.uky.edu/en/publications/analytical-modeling-of-magnetic-fields-and-winding-factors-for-co/) | The university record identifies this 2026 work as accepted/in press, with coreless axial-flux winding and prototype validation. It is relevant research context, not evidence that this workbench implements or validates those axial-flux topologies. |

## Winding layout

The layout contains two conductor layers, explicit coil start/return slots, polarity, phase and series turns. Concentrated tooth coils use one-slot pitch. Chorded coils use less than a full pole pitch. Distributed layouts retain the selected pitch. Each harmonic winding factor is computed from the signed coil-side phasor sum; a label alone does not determine the result.

The tool checks coil counts, fundamental magnitudes and phase axes before allowing motor calculations. An unbalanced slot/pole/phase combination remains inspectable but cannot masquerade as a balanced simulated machine. Winding harmonic factors are not a prediction of cogging or torque ripple.

Odd phase counts use full-cycle symmetric axes. Even phase counts use distinct half-cycle axes with independent phase drives, including 90-degree two-phase quadrature. This is not a claim of a common-neutral connection or an arbitrary dual-three-phase winding. End-turn packaging, insulation and manufacturing constraints still require layout review.

## Flux, EMF and force

For a sinusoidal air-gap fundamental, rotary pole flux is `2 B1 length radius / pole_pairs`; the linear counterpart is `2 B1 length pole_pitch / pi`. Series turns and the calculated winding factor give each phase's peak flux linkage. Permanent-magnet mode can estimate B1 from explicitly entered remanence, magnet thickness, air gap, recoil permeability and pole arc, using an equal-area, infinite-iron-permeability magnetic circuit. Supplied B1 also supports a wound-field synchronous baseline; rotor excitation is not solved automatically.

With phase linkage `lambda_j(q)`, induced EMF is `speed * d(lambda_j)/dq` and electromagnetic effort is `sum(current_j * d(lambda_j)/dq)`. Position q is radians for rotary machines and metres for linear machines. This construction enforces `sum(e_j i_j) = torque * angular_speed` or `force * speed`. It avoids mixing electrical/mechanical angle, peak/RMS current or linear/rotary constants.

The baseline omits saliency/reluctance torque, iron and switching losses, saturation, cogging and finite-length end effects. A 2025/2026 reference in the documentation does not turn these omissions into supported physics.

## Phase events and small simulations

EMF peaks and zero crossings are reference events derived from the phase axes and electrical speed. They are not ready-to-flash gate commands: inverter topology, current control, dead time, encoder alignment and sensor delays are separate requirements.

Small mechanics simulations run through KiCad ngspice transient analysis using ideal position-synchronous phase currents and declared inertia/mass, damping and opposing load. Their unlimited current-source voltage compliance is explicit. They do not simulate acquisition of synchronism, an inverter or a closed current loop.

## Verification

Standard references include a 36-slot/4-pole distributed three-phase winding with fundamental factor 0.95979508, and a 12-slot/10-pole concentrated winding with factor 0.93301270. Tests compare EMF to flux-linkage derivatives, check electromagnetic/mechanical power equality, reject unbalanced configurations and examine time-step refinement against the constant-effort damped-motion solution. See the release audit for the actual test evidence.


A native ngspice 46 reference used 0.01 kg m² inertia, 0.02 N m s/rad damping and 0.345526228989 N m constant electromagnetic torque for 0.2 s, with 0.1 ms maximum step. Final speed was **5.695653577991 rad/s**, against **5.695653563322 rad/s** analytically (2.58e-9 relative error). Position error was 1.21e-8 relative. An independent RK4 implementation supplies a time-step refinement cross-check. These tolerances concern the linear mechanical equations, not the fidelity of the ideal electromagnetic excitation. [Recorded motor references and phase presets](audits/MOTOR_REFERENCE.json).
