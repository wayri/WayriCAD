# WayriCAD 4.0.1

Quick PI and Quick SI are easier to set up and inspect, while keeping the board
as the main workspace.

- **Quick PI:** clearer feedback about missing source/load inputs, changed board
  files and unsupported mode combinations before running. Loss/probe tables can
  copy selected rows or the complete table with full values.
- **Quick SI:** the header describes the route or study case actually on screen,
  including delay and eye-model availability. An unavailable eye keeps the route
  visible and explains what needs attention.
- **Quick EMerge (beta):** full-area 2D/3D geometry views focus on the antenna
  region without graph framing. A results toggle keeps solved data available;
  charts and detailed controls open on demand. One Export
  menu saves 2D plots, current 3D views and HTML/PDF reports.
- **Board-derived SI eyes:** the selected route's extracted R/L/C sections now
  drive the linear PRBS7 eye and step response. Width changes retain their
  reflections; receiver capacitance and reviewed via equivalents are explicit
  inputs. Missing geometry and failed numerical convergence remain unavailable.
  [Setup and model limits](../signal_integrity_advisor_plugin/BOARD_RLC_EYE.md).
- **Fanout guide:** pictures and explanations for all 16 styles plus via-in-pad,
  grouped by component family. [Visual catalogue](../fanout_generator_plugin/ReadMe.md#fanout-style-catalogue).
- Updated quick-tool help, native screenshots and the independent packages.

The SI eye includes DC copper resistance and quasi-static L/C. Skin-effect and
dielectric loss, nonlinear IBIS and full LPDDR4 training/ODT/timing are not
included. Quick EMerge and Review retain their testing status. Existing source
checks, read-only analysis and large-viewport layouts remain in place.

[Validation scope and screenshots](audits/QUICK_TOOLS_POLISH_4.0.1.md).
