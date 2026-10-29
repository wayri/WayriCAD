# WayriCAD 3.6.46

Quick EMerge opens around its viewport, fanout has new perimeter patterns, and
Quick PI adds reviewed setup workflows.

- **Quick EMerge (beta):** full-width viewport by default, toggleable Setup,
  compact Preview/Run/Cancel actions, optional inspector and preserved panel
  state. The viewport area grows 44% at the tested 1120 × 780 window size.
  [Screenshots and guide](../quick_emerge_plugin/README.md).
- **Fanout Generator:** alternating short/long perimeter escapes and alternating
  inward/outward escapes for QFP/QFN-style banks. Inward candidates still have
  to clear actual pads, exposed pads, keepouts and other geometry. Advanced
  controls include dimension illustrations, and opening them retains window
  size. Styles are grouped into perimeter, grid, connector and general/custom
  families with advisory guidance from the actual selected pad layout. [Patterns and limits](../fanout_generator_plugin/advanced-fanout.md).
- **Quick PI returns:** shared ground contacts accept multiple mapped load
  demands and sum currents at the common electrode. A load at supply ground
  retains its current with zero return drop. Supply/load overlap protection
  remains strict for ordinary solves. Pad pickers can check the same-net pins
  of the highlighted component without losing hidden search selections.
- **Series current terminals:** select reviewed pad pairs/groups on multipad
  parts, including explicit source and sink groups. One component model and
  total current apply to the whole electrode; gate/control pins remain excluded.
  [Setup and supported modes](../quick_pi_plugin/SERIES_PAD_GROUPS.md).
- **Reviewed power tree:** edit energy flow, converter roles, signed rails,
  explicit returns and isolation domains. Metadata-backed suggestions remain
  unreviewed. Arrows do not turn ICs into resistors or short isolated grounds.
  [Workflow and CLI](../quick_pi_plugin/POWER_TREE.md).
- **Post-solve spacing screen:** multi-net results can be compared against
  explicit applicable rule, material, environment and voltage assumptions, with
  closest-point markers and board net selection. Planar copper clearance is
  distinct from physical surface creepage; missing surface measurements remain
  unknown. This is engineering screening, not insulation certification.
  [Workflow and CLI](../quick_pi_plugin/INSULATION_SCREEN.md).
- **Thermal materials:** QuickTherm and PI electrothermal setup can apply checked
  properties from an editable source-backed library. Unknown properties and
  unspecified reference conditions stay explicit. [Sources and units](THERMAL_MATERIALS.md).
- **PI reliability:** editor-connected selection prepares the KiCad IPC dependency;
  simulation saves capture the actual producer version. An optional portable
  export cannot turn an otherwise saveable result into fabricated provenance.
- **Multiple editors:** runtime handoffs retain the launching editor's socket
  and token as one captured pair. Connections authenticate before loading live
  operations. A token mismatch explains recovery instead of switching boards.
  The Windows shared-endpoint collision still requires launching editors in
  separate temporary namespaces; see [troubleshooting](TROUBLESHOOTING.md#windows-two-open-editors-and-an-unreachable-second-instance).

Quick EMerge remains an exploratory testing beta. Numerical convergence and
paper-reference qualification are pending. Fanout creates escape endpoints,
not complete routed connections: native DRC still reports dangling endpoint
vias in the synthetic fixtures; those findings were retained, not suppressed.
The PI power tree records reviewed intent, not a nonlinear converter simulation.

### Simulation setup and result files

- Quick PI, SI and Therm now provide separate setup Save/Load controls. File choosers start in the saved PCB project folder and let you choose another location or filename. Quick PI’s AC, transient, electrothermal, multi-rail and PDN studies retain their own input files.
- Complete simulation JSON can be saved under a readable chosen name and reopened read-only, including Quick EMerge beta results. Plugin, schema and content checks preserve arrays and identify stale/unverified source data. CLI supports the same named files.
- Loading setup validates mappings before applying them, clears old results, and asks for explicit review when the board revision changed. Original boards and declared study/model input files are protected from result-file overwrite.
