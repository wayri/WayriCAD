# WayriCAD 3.6.17

Long net names are easier to read, and Fanout Generator can now route connector pins to the connector edge.

- Wider Windows dropdowns and complete-value tooltips in Quick PI, Quick SI, QuickTherm, Trace RLC, Extract Pins, Harness, Fanout and Via Stitching. Editable filters retain their full text.
- Connector-edge breakout supports SMD and plated through-hole pins, selected pins/nets, footprint-local exit sides and obstacle-aware paths. Bottom-layer routing from a through-hole pin avoids unnecessary source vias.
- Optional local clearance exports a separate PCB/project/rules review copy. The working board stays unchanged; board minimums and higher-priority source rules remain. Review the copy with native KiCad DRC.
- CLI plans retain connector geometry and reject changed saved custom rules or netclasses.

The 17 IPC packages advance to 3.6.17. Fusion 0.9.8 and Variant Manager 0.6.1 keep their existing published package bytes. Refresh the WayriCAD repository in KiCad PCM, update the desired plugins and restart PCB Editor.

A synthetic 78-pin staggered connector routed all pins; native DRC found only the expected open-stub warnings. This does not certify a particular connector, protocol or manufacturing process. Connector mode uses independent pins; paired-channel routing uses the existing pair styles. Search is bounded and blocked pins remain explicit.

See the [connector workflow](../fanout_generator_plugin/ReadMe.md#connector-edge-breakout), [feature validation](audits/connector-edge-dropdowns.md) and [release checks](audits/RELEASE_3.6.17.md). Other wx platforms keep their native popup sizing and full-value tooltips; their GUI behavior was not visually validated in this release.
