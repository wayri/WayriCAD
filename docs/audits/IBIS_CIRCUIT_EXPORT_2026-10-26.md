# IBIS circuit export and computed thermal playback

## Implemented circuit model

Quick SI records a whole-net routing inventory against its ordered selected path.
A circuit requires two signal pads, matching item UUIDs, kinds and lengths, no
uncovered branches/stubs or signal zones, and fresh saved design/rule hashes.
The parser reads bounded IBIS component, physical pin, model-selector and model
role metadata. Exact endpoint mapping and reviewed vendor SHA-256 are required;
the parser does not validate electrical tables. KiCad interprets the IBIS data.

Each track section becomes a native distributed lossless line with Z0 and delay
plus its DC series resistance. Native IBIS sources and receivers replace the
screen's resistive endpoints; package parasitics remain in KiCad's IBIS model,
without duplicate external package RLC. Via sections require explicit consent,
complete-loop inductance in nH and shunt capacitance in pF. A copper-thickness
fallback is marked as such; exporting it requires reviewed thickness in µm and
explicit Z0/effective-permittivity assumptions. Resistance scales inversely with
thickness, and delay is length times sqrt(effective permittivity) / light speed.
Saved stackup geometry retains its derived values.

Cases share an ideal ground but have separate signal nets. There is no solved
return impedance, simultaneous switching, coupled multi-net channel, skin loss,
dielectric dispersion, pad discontinuity or board qualification. Unsupported or
missing data fail visibly instead of receiving plausible defaults.

The bundle contains the project, indexed channel sheets, authored cached symbols,
library table, unchanged model copies named by SHA-256 and a manifest. The flat
clipboard includes every selected case's real circuit objects and cached symbols;
it uses absolute bundled-model paths so it can be pasted elsewhere. Keep that
bundle. Fresh exports use distinct signal namespaces; repeated paste of one
fragment shares global names. Publication is staged and guarded against changed
models, design, report or assignment documents. No PCB geometry is written.

## Native and real-board checks

Windows, KiCad 10.0.6, bundled Python 3.11.5 and wxPython 4.2.2 were used for native
checks. Source regression runtime is Python 3.14.2. Native schematic properties
follow KiCad's own IBIS, transmission-line and clipboard contracts:

- [KiCad IBIS implementation](https://github.com/KiCad/kicad-source-mirror/blob/10.0/eeschema/sim/sim_model_ibis.cpp)
- [KiCad transmission-line implementation](https://github.com/KiCad/kicad-source-mirror/blob/10.0/eeschema/sim/sim_model_tline.cpp)
- [KiCad schematic clipboard implementation](https://github.com/KiCad/kicad-source-mirror/blob/10.0/eeschema/tools/sch_editor_control.cpp)
- [IBIS 7.1 specification](https://ibis.org/ver7.1/ver7_1.pdf)

These are implemented native API contracts, not a claim to implement the entire
IBIS specification independently. Vendor files are not redistributed with tests.

| Public Marble route | Length | Sections | Vias | Native routing inventory |
|---|---:|---:|---:|---:|
| MDC | 253.670353 mm | 34 | 3 | 34 items, all accounted |
| LED14 | 252.483153 mm | 30 | 3 | 30 items, all accounted |

Fresh analysis rejected MDIO for three signal pads and LED13 for one off-path
track. The two accepted paths exported 144 components: 2 drivers, 2 receivers,
64 resistors, 58 distributed lines, 6 inductors and 12 capacitors. Native SPICE
and XML inventories matched; both source-to-sink series chains were continuous;
ERC reported zero violations across five sheets. Five native SVG pages and a
144-instance flat clipboard were generated. A stale model SHA was rejected
without an output bundle. Marble source SHA-256 before and after was
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.

The integration used KiCad's stock demo IBIS with explicit mappings, 50 Ω,
effective permittivity 4, 35 µm copper and 1 nH/1 pF via assumptions. These are
synthetic integration inputs, not actual Marble device models or measured via
parameters. They prove export connectivity and format, not channel accuracy.
A separate synthetic circuit ran KiCad-generated IBIS models with ngspice 46:
400 ns, 5 MHz stimulus, 0.1 ns maximum step, 6,718 finite samples. The demo's
30 ns edges cannot support the default 100 MHz stimulus; native simulation
correctly requires compatible timing. User vendor models need their own checks.

## Clipboard parser checks

The latest two-case synthetic bundle passed native XML, SPICE, SVG and ERC
exports, with zero ERC violations. The unchanged flat clipboard payload was
wrapped in a differently named native project, without its library table.
Native parsing preserved all 12 symbols, values, simulation fields and 11 net
memberships. All four absolute IBIS links resolved to unchanged model copies;
SPICE export succeeded. ERC in that unrelated project reported 12 missing-library
registration warnings and zero errors. Register the bundle's `quicksi.kicad_sym`
in the target project's symbol libraries to clear those consistency warnings.
Cached symbols retain the circuit and simulation properties meanwhile.

An actual interactive Ctrl+V, placement and reannotation were not observed;
validation used KiCad's native parser/exporter on the exact clipboard objects.
Separate-export signal names are disjoint. Native sandbox ERC initially failed;
the identical target passed unrestricted native ERC. These checks distinguish
native file compatibility from an observed live-editor paste workflow.

## Thermal frame changes

The spatial backward-Euler solver lands on requested output times and power
schedule events. Default native studies store 101 computed frames over 10 s at
0.1 s spacing. Solver maximum step and output interval are independent. Native
and offline viewers expose Previous/Next and speed controls; fast playback may
skip displayed frames, while each stored frame remains individually selectable.

Limits are 1,000 explicit-interval frames, 10,000 integration steps and five
million stored node values. Requests over the limits fail with guidance rather
than silently coarsening. Legacy stride-based studies retain their 200-frame
limit. Fixed temperature scales, camera and probes persist during playback.
Native air/vacuum examples each produced 101 frames; maximum energy residuals
were 1.27e-13/1.22e-13 W, and source bytes remained unchanged. These are numerical
conservation checks under declared example inputs, not thermal qualification.
