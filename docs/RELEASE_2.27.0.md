# KiWay v2.27.0 Release Notes

## Differential-Pair Intelligence

A shared pattern detector now recognises pair nets across the suite via
`_P/_N`, `_DP/_DN`, `_DP/_DM`, `+/-`, `_+/_-`, and guarded `P/N` tails,
case-insensitively and with rule labels:

- Trace RLC Analyzer auto-fills the differential mate when a net is chosen,
  measures both legs through the standard impedance models, reports
  intra-pair skew against the 0.5 mm guideline, and draws the mate lane in
  the Route Preview with its own legend entry.
- Signal Integrity Advisor auto-selects the detected mate for the primary
  net, states the matched rule inline, and keeps manual override available.
- Return-Path Auditor differential gap/skew checks now use the shared
  detector (with the previous suffix fallbacks preserved).

## Cross-Selection and Highlight

- Shared canvas plumbing supports clickable scene picks plus persistent
  highlight markers; clicking a preview item cross-selects it in PCB Editor
  and highlights its net across KiCad API variants.
- Trace RLC and Signal Integrity previews: click any routed segment to
  select and highlight that net; Trace RLC adds a Highlight Net on PCB
  action covering both pair legs together.
- Return-Path findings sync both ways: double-clicking a table row marks
  the finding in the preview map, and clicking a preview marker selects the
  matching row, selects the net's copper, and highlights the net.
- PDN placement map pads are clickable with footprint selection, net
  highlight, and a visible highlight ring kept on the picked pad.

## Package Updates

Trace RLC 0.8.0, Signal Integrity Advisor 0.3.0, Return-Path Auditor 0.3.0,
PDN Planner 0.3.0. Suite version 2.27.0.

## Safety

Detection is name-based only; no state or direction is inferred beyond the
declared patterns, and every PCB write still requires an explicit staged
preview and confirmation as before.
