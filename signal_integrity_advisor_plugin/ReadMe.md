# KiWay Signal Integrity Advisor

This modeless PCB Editor plugin provides two guarded, read-only workflows:

- calculate the permissible I2C pull-up resistance range from bus voltage, total capacitance, rise-time limit, sink-current capability, and low-level voltage;
- measure an explicitly selected routed path against an editable single-ended or differential impedance target.

The impedance estimate uses the KiCad board stackup, chosen reference layer, routed copper width/length, vias, layer transitions, and zones available through `pcbnew`. It is a first-order design check, not a substitute for a 2D/3D field solver, TDR, or protocol compliance test.

Open a PCB, launch **KiWay Signal Integrity Advisor**, select a workflow, review all inputs, and run the check. A result is never marked passing when the start/end route cannot be resolved.

