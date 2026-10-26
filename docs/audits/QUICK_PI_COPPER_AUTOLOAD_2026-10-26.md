# Quick PI first-open copper display

The initial window previously queued physical geometry extraction after reading
its inventory. That made display depend on solver stackup and domain checks,
and net changes could leave only saved silkscreen visible. Layer choice could
also land on a layer without the selected net's copper.

Startup now reads inventory and saved display copper in one background worker.
The view selects an occupied layer, retains copper independently of the Board
visibility checkbox and uses normal preview opacity before a field exists.
Changing nets filters the cached scene and selects an occupied layer if the old
layer is empty. The combined-layer choice remains available. Exact simulation
geometry is prepared by Preview/Run; no material values are guessed and startup
creates neither a mesh nor an electrical result.

Quick PI omits fabrication and courtyard display polygons because its viewport
already excludes them. The shared renderer's default still includes those layers
for other callers. Native tests show all remaining primitive bytes are identical
to the corresponding subset of the full scene. No source copper is modified.

## Checks

Windows, KiCad 10.0.6 / bundled Python 3.11.5 / wxPython 4.2.2:

- 27 native startup, viewport, layer/scope and display-cache tests passed.
- Six shared native display tests passed, including saved fill voids, holes,
  exact net ownership and the optional fabrication filter.
- An unpublished independent Quick PI ZIP passed 11 native tests with zero
  skips; all 24 loaded production/runtime module bytes matched that archive,
  with imports restricted to the extracted payload. Tests were copied externally;
  installed editor registration/live IPC was not exercised.
- A real background subprocess and native frame loaded a disposable board in
  1.66 s without starting a simulation. The installed native interpreter was
  supplied instead of invoking managed-runtime setup.
- The same read-only startup path on public Marble displayed +12V on F.Cu,
  with 1,374 nets and 179,131 retained display primitives. The observed first
  load was 29.48 s; dense-board first-load latency remains substantial. An earlier
  full-artwork run took 33.98 s. These single runs are not a controlled speedup
  benchmark. The original PCB hash was unchanged.
- The portable Quick PI suite had 350 passes, 61 skips and 399 subtests, with one
  subprocess test failing because its inherited Windows handle was invalid.
  That test and all seven display-cache tests subsequently passed with a valid
  console handle. The numerical solver was not changed.

README/offline help describe initial saved copper separately from simulated
geometry. Published 3.6.32 binaries and the public PCM feed are unchanged by this
source fix; a future software release must rebuild and validate its own assets.
