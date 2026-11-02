# Series result overview regression

Trigger: run an explicit series path after previewing its source net on a physical
layer. The result handler retained that layer, hiding solved copper on other
layers. A completed series study now initially selects the all-layer projection.
The read-only archive viewer similarly starts on a combined potential plot when
the saved series mesh contains multiple supported planes. Neither path reruns or
changes the numerical solution.

Windows validation, KiCad 10 native Python 3.11.5:

- Two native unittest checks passed. A real Quick PI wx frame accepts a solved
  three-net/two-layer analytical fixture after source-layer selection, opens all
  copper layers, fits the downstream extent, and retains both components.
- The actual read-only archive window opens the full-path projection.
- Save/load retains every triangle and exact voltage, and leaves payloads
  unchanged. Exact stored-plane plots remain available.
- This is a hidden native window and analytical fixture check, not interaction
  with the user's live PCB Editor or a new KiCad 11 editor matrix.

Portable focused checks: 49 passed, one native check skipped, 12 subtests passed.
Source documentation validation and diff whitespace checks passed.

Regression: `quick_pi_plugin/tests/test_series_result_overview.py`, included in
the CI Quick PI step. Existing unknown/topology/budget restrictions remain active;
no geometry between disjoint sections is synthesized.
