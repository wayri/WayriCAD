# WayriCAD 4.1.1

Quick PI now opens completed series results with **All copper layers
(projected)** selected. Previously a physical layer retained from the source-net
preview could hide downstream copper on other layers, making the result appear
to contain only the first segment. Physical layers remain selectable for precise
inspection. Solver calculations and stored numerical values are unchanged.

Reopened series simulations start with a complete-path potential overview while
retaining the individual saved plane plots. Overlapping projected values are not
summed; ambiguous probes remain explicit. Existing saved simulations need no new
solve to use the overview.

The regression uses a solved three-net path across two copper layers, checks all
triangles and exact voltages through save/load, and exercises the native KiCad 10
post-run and read-only saved-result windows. KiCad 11 remains experimental; this
hotfix does not establish a new native KiCad 11 qualification.
