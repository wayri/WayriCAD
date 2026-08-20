# KiWay Harness and Cable Workbench 0.2.0

Builds a system-level harness definition from as many as 50 board pin exports.
It supports indexed net matching and connector correspondence where pin 1 maps
to pin 1, pin 2 to pin 2, and so on. Offset and explicit pin maps cover
connectors whose numbering differs.

The workbench produces sortable wire, pin, net, and procurement tables; a
native pan/zoom system draft; and CSV/SVG outputs. Harness-only loads can be
entered without adding artificial components to a schematic. Selected wires
can be assigned gauges, colors, lengths, shields, bundles, and splices.

Connector rule examples:

~~~text
DEMO_CTRL:J1 -> DEMO_IO:J2
DEMO_IO:J4 -> LOADS:P1 [offset=1]
DEMO_A:J3 -> DEMO_B:J7 [map=1:3,2:4]
~~~

Automatic matching establishes correspondence, not electrical or mechanical
compatibility. Independently verify polarity, mating view, pin gender, wire
ampacity and derating, insulation, creepage, shielding, bend radius, connector
ratings, assembly process, applicable standards, and test coverage.
