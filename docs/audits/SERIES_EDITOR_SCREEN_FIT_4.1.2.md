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
- Focused portable editor/session/group checks: 31 passed.

The disposable live-editor fixture contains VIN → MID → OUT on front/back/front
copper, two series stages, one additional parallel device per stage, and two pins
in every source, load and component current electrode. It has 20 reviewed current
pins and four excluded control pins. Native DRC reported zero unconnected items;
four fixture findings remain (two overlapping control-pad pairs outside the
solved path and two overlapping reference labels). This is a workflow fixture,
not a manufacturing-qualified board.

The full live-editor solve and setup/simulation save-reload validation is pending.
Desktop automation was blocked by a locked Windows desktop while the candidate
was prepared. Hidden native regressions do not establish that workflow as passed.
