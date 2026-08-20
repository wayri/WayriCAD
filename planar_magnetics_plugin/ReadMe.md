# KiWay Planar Magnetics & Actuator Workbench 0.2.0

Generate rectangular or circular planar windings across as many as 16 copper
layers with series transitions, stitched vias, separate primary/secondary PCB
nets, independently layered secondary turns, and an extensible JSON magnetic-core catalog. The workbench
estimates DC/AC resistance, inductance, capacitance, self resonance, Q, copper
and core loss, saturation, coupling, field, force, and magnetic-torquer torque.

The coupled motion solver integrates coil current and a one-degree-of-freedom
mechanical model. Inputs include moving mass or rotary inertia, restoring
stiffness, damping or mechanical Q, initial magnetic gap, hard travel limits,
external load, static friction, waveform, drive frequency, simulation duration,
time step, and temperature. Results include force or torque, transduction
constant, force gradient, acceleration, speed, displacement, resonance,
settling, thermal force-noise density, and Brownian displacement.

Actuator modes cover voice coils, linear solenoids, PCB coil motors, and PCB
magnetic torquers. Macro and nanoscale screening presets are provided. The
nanoscale preset is not a fabrication signoff model: it omits rarefied-gas and
squeeze-film damping, adhesion, stiction physics, Casimir and van der Waals
forces, process stress and geometry variation, nonlinear material properties,
multimode coupling, readout back-action, and quantum effects. Use
process-calibrated electromagnetic/structural/fluid/thermal FEA and measured
device parameters before fabricating MEMS or NEMS hardware.

Temporary PCB previews are removed when the window closes. Accepted windings
are stored in persistent named groups, allowing the latest KiWay commit to be
undone after reopening the workbench.
