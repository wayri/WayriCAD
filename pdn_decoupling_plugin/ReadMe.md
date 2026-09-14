# WayriCAD PDN and Decoupling Planner 3.0.0

Finds configured load power pins that do not have a nearby capacitor connected between the same rail and a configured ground net. Regulator candidates are inferred from component values using editable keywords. Results cross-select the load footprint and export to CSV.

Distance is only a screening metric. The plugin does not solve frequency-dependent plane impedance, anti-resonance, capacitor ESL/ESR, package inductance, transient droop, current density, or thermal behavior.
