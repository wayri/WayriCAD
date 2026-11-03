# Series editor screen fit

Observed in a real KiCad 10.0.6 PCB Editor session on Windows: the released
4.1.1 Quick PI toolbar action opened its companion on the disposable
`series-parallel.kicad_pcb` test board. At the active display scaling, the series
dialog extended below the display and hid Load path, Save path, Run and Cancel.
The dialog's minimum-content sizing made the footer inaccessible.

The candidate constrains the outer dialog to the parent display's work area.
Inputs use a scrolling child; the footer stays outside it. Both horizontal and
vertical overflow remain reachable. No topology, model, pin identity or solver
logic changed.

Performed checks:

- Native KiCad 10 Python 3.11.5/wx: constrained 1200 × 700 work area, footer
  visibility and bounds, overflowing content and actual scroll position passed.
- Existing native saved-series setup/draft controller regression passed.
- Focused checks: 35 passed, one skipped, 26 subtests.
- Extracted PCM native checks: three passed, with exact archive module bytes.
- All eight CI jobs passed on release source
  `dbcd065b56d9b421ca49b416bf681d8e2d458be8`.

The disposable live-editor fixture contains VIN → MID → OUT on front/back/front
copper, two series stages, one additional parallel device per stage, and two pins
in every source, load and component current electrode. It has 20 reviewed current
pins and four excluded control pins. Native DRC reported zero unconnected items;
four fixture findings remain (two overlapping control-pad pairs outside the
solved path and two overlapping reference labels). This is a workflow fixture,
not a manufacturing-qualified board.

Live-editor acceptance completed on Windows with KiCad 10.0.6 and its Python
3.11.5 runtime, after the source and package build were frozen. The exact 4.1.2
PCM payload launched through the PCB Editor toolbar. The series footer remained
reachable. Preview showed Q1 || Q2 and Q3 || Q4, including input pins 1/2 and
output pins 3/4 for each device, source J1.1/J1.2 and load J2.1/J2.2. Closing and
reopening the series dialog retained the draft. Control pin 5 remained excluded
on all four devices.

Run completed at 3.3 V and 2 A: approximately 276.1 mV drop, 138.1 mΩ circuit
drop/current and 0.5523 W loss. The live result automatically selected all copper
layers projected and displayed all three segments. Setup and simulation were
saved through their actual file dialogs. After closing the companion and
relaunching from PCB Editor, Load setup restored every stage, parallel model and
pin group. Rerunning and saving again produced exactly equal setup state and
entire simulation JSON, including request, geometry, mesh, numerical result and
terminal groups. All 20 unique current pins were retained.

Load simulation opened the read-only saved viewer at “Complete series path / all
copper layers (projected) / potential_V”; all three copper sections were visually
confirmed. The PCB file hash remained unchanged. Local fixture files and detailed
test records are excluded from release assets. Acceptance updated only release
evidence; the CI-passing release binaries were unchanged. No fresh native KiCad
11 qualification was performed; its support remains experimental.
