# Native help visuals — 3.6.38

Captured 27 October 2026 on Windows, KiCad 10.0.6, Python 3.11.5 and wxPython
4.2.2. These are native application client-area captures using RGB24
`wx.ClientDC`, not mockups. No image retouching or redaction was performed.
They exercise source windows with saved-board fixtures, not installed ZIPs or
editor-connected lifecycle workflows. Blank PrintWindow outputs were rejected.
Earlier large showcases remain available; these images supplement them.

## Sources and scope

- Public Marble: `/ETH_PHY/MII_MDC`, U6.8 to U54.16, 253.670 mm,
  31 tracks and three vias. Source SHA-256:
  `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
  Saved source bytes were unchanged after SI, RLC and Bulk captures.
- Quick SI: declared 50 Ω, effective permittivity 3.2, 1 ns rise time,
  20 Ω source, 50 Ω receiver, 100 MHz and explicit GND reference. Delay
  1.513645 ns uses those assumptions; it is not extracted channel validation.
- SI neighbours: three synthetic straight DATA/CLOCK/RESET tracks, three pairs;
  DATA/CLOCK gap 0.3 mm and parallel length 30 mm. NEXT remains UNKNOWN without
  local reference/material/edge inputs. Geometry search is not a field solve.
- RLC: the same Marble path at 100 MHz, DC resistance 0.978676 Ω. PARTIAL:
  unresolved reference coverage and via antipad capacitance; modelled-only
  L/C totals are not a complete return-loop equivalent. Via plating assumes
  25 µm. No full path Z0 is asserted.
- QuickTherm: public `quick_therm_plugin/examples/thermal-demo.kicad_pcb`,
  four included parts, declared 1.05 W total, ambient 20 °C, effective
  thin-sheet k=35 W/(m K), emissivity 0.8 and airflow 10 m/s. Automatic mesh
  has 600 cells. These are steady thin-sheet results, not CalculiX or transient
  qualification. STEP solids are off. Paired faces show one approximate
  midplane field; this demo has no bottom-side components.
- Bulk: 35,765 text fields, 1,374 named nets. `^R(16[0-9])$` → `X\1`
  previews ten reference replacements; Apply was never invoked. The net
  browser displays the same public MDC connection.

## Published current captures

All listed PNGs are opaque RGB, have no embedded metadata, and were visually
inspected. Visible titles, controls and result labels contain no personal paths.

| Image | Pixels | SHA-256 |
|---|---|---|
| [quick_therm_plugin/examples/quicktherm-input-3.6.38.png](../../quick_therm_plugin/examples/quicktherm-input-3.6.38.png) | 1460×810 | `bcf7e1e9a08202066d95a447e58b3cc744fb859d85be84bd451230492f283929` |
| [quick_therm_plugin/examples/quicktherm-3d-3.6.38.png](../../quick_therm_plugin/examples/quicktherm-3d-3.6.38.png) | 1460×810 | `1c0eb51d6b0b239412a99edd0b4e5a52a1b4f31d9fcaca575290d2dc00f1d850` |
| [quick_therm_plugin/examples/quicktherm-paired-3.6.38.png](../../quick_therm_plugin/examples/quicktherm-paired-3.6.38.png) | 1460×810 | `5afeb9f5ad99789f80d0733f784f340c97dc2e754dded02e8819283bba853f6d` |
| [signal_integrity_advisor_plugin/help-quick-si-3.6.38.png](../../signal_integrity_advisor_plugin/help-quick-si-3.6.38.png) | 1452×819 | `761888bdc40719fa5f051a873c8e87a21a9777dd24bc4e97166602695adac970` |
| [signal_integrity_advisor_plugin/help-neighbours-3.6.38.png](../../signal_integrity_advisor_plugin/help-neighbours-3.6.38.png) | 1084×781 | `83c8f052264884bda19cf08d500042358b419a0642b6a1d9bd331972bfa609e3` |
| [trace_impedance_plugin/help-path-3.6.38.png](../../trace_impedance_plugin/help-path-3.6.38.png) | 1452×819 | `9f910f739047e24f869facd08c92384e410f89a437188b859e056e36f6fa860c` |
| [trace_impedance_plugin/help-results-3.6.38.png](../../trace_impedance_plugin/help-results-3.6.38.png) | 1452×819 | `d0518c864b875124e89a0f9546082f2c0b76c06504a0edf6a960e2e60cc564ac` |
| [bulk_label_editor_plugin/help-preview-3.6.38.png](../../bulk_label_editor_plugin/help-preview-3.6.38.png) | 1364×781 | `200f69e5816f55713abd1897f2a070aae9e9a5c3a8a7a492dc9f38f77ec3799a` |
| [bulk_label_editor_plugin/help-nets-3.6.38.png](../../bulk_label_editor_plugin/help-nets-3.6.38.png) | 1364×781 | `4e9c4e649a903f50ef99fd86419bb6c4ee0dc7361494c026bf676b19aafbfda3` |
| [quick_pi_plugin/help-mixed-loads-3.6.38.png](../../quick_pi_plugin/help-mixed-loads-3.6.38.png) | 1452×819 | `ed6e5e348d43feb6a9bc60a017df6befd41033f117ba982d690e921761624e7b` |
| [quick_pi_plugin/help-inspector-tables-3.6.38.png](../../quick_pi_plugin/help-inspector-tables-3.6.38.png) | 1304×761 | `b7853bf15693c863092aea6cbf0b63fa5222f296f74be5d7b9b0168e27e0e718` |
| [quick_pi_plugin/help-loss-tables-3.6.38.png](../../quick_pi_plugin/help-loss-tables-3.6.38.png) | 1304×761 | `7a465a1c565571820858376d8592f3d587b7feef5fa10788e4d637ce8d22c803` |
| [quick_pi_plugin/help-heating-tables-3.6.38.png](../../quick_pi_plugin/help-heating-tables-3.6.38.png) | 1304×761 | `569ffd9883dbb370d070b6008b937af462aab3909e9692c25817002aca784c20` |
| [quick_pi_plugin/help-transient-setup-3.6.38.png](../../quick_pi_plugin/help-transient-setup-3.6.38.png) | 1364×861 | `6181ae9aaa39a2f66c526e99b0e04ee37a7103616c2be41153cf920627a0f120` |
| [quick_pi_plugin/help-transient-results-3.6.38.png](../../quick_pi_plugin/help-transient-results-3.6.38.png) | 1364×861 | `c679fe44cd9e9c5fa2012c1ed1459be23d4aa15af07cd279f2fb21004bc2f97d` |
| [quick_pi_plugin/help-pdn-setup-3.6.38.png](../../quick_pi_plugin/help-pdn-setup-3.6.38.png) | 1364×861 | `372cd5650a80895446e763d933b8a9ed8c3d2236bdc393cf3e8c905dcd5f3579` |
| [quick_pi_plugin/help-pdn-results-3.6.38.png](../../quick_pi_plugin/help-pdn-results-3.6.38.png) | 1364×861 | `7abdd0ea354da1a360e7a69223e036b7e5e8103e8361a4c77a0108c4e2b11e24` |
| [quick_pi_plugin/help-ac-setup-3.6.38.png](../../quick_pi_plugin/help-ac-setup-3.6.38.png) | 1364×861 | `42b9dfe04aa7d04f2e93b639d775e29d855ec523bf1e11f480219277e081e69d` |
| [quick_pi_plugin/help-ac-results-3.6.38.png](../../quick_pi_plugin/help-ac-results-3.6.38.png) | 1364×861 | `7ff93bf9539fb062d83f2f847ac03b69e60abe3d7a9bb0833ee1cbc904aca673` |
| [heater_designer_plugin/help-workflow-3.6.38.png](../../heater_designer_plugin/help-workflow-3.6.38.png) | 1364×801 | `81ba17fccea5cb463ecb0b3bd4cee9fb6d31c21b87992d1cd903c5ca5a0b1ce6` |

## Quick PI current examples

- Mixed load: disposable 10 mm × 1 mm copper strip with J1.1/J1.2 source
  and U1.1/U1.2 ideal equipotential sink groups. At 3.3 V, U1 consumes
  1.65 W and U2 consumes 0.25 A. Actual saved-board extraction, VTK mesh,
  explicit 35 µm copper stackup, 293 nodes/502 triangles. Total source current
  0.750252095 A, U1 3.298337013 V, U2 3.297782870 V, copper loss
  1.386195 mW and relative energy error 1.98e-13. Fixture hash
  `1e49d64d28ac5595690b8899776de797081825c2507fc0b3681c96c761cda771`
  stayed unchanged. Mesh convergence was not established.
- Inspector/loss/heating tables: analytical 10 mm × 1 mm × 35 µm copper
  strip, 1 V and 2 A, 33 nodes/40 triangles, fixed-temperature DC. Native
  regression checks sort and exact cell/map identity cross-selection. Four
  inspector tests passed. The scene is a disposable one-track saved board;
  field data comes from the analytical strip fixture. Boundary-node labels
  are solver markers, not physical components. Pulse results are adiabatic
  screens and omit cooling and fuse-opening dynamics.
- Transient: explicit lumped network, 3.3 V, shared R=10 mΩ/L=5 nH;
  U1 step 0.1→1 A at 10 µs, branch R=5 mΩ/L=1 nH, C=100 µF,
  ESR=10 mΩ, 100 µs duration, 0.1 µs step. Actual transient solve has
  1,002 samples. This is not a PCB-distributed or regulator-control model.
- PDN: illustrative R=20 mΩ/L=5 nH source, one effective 100 µF
  capacitor with ESR=10 mΩ/ESL=1 nH. Target is 50 mV/1 A = 50 mΩ.
  Actual lumped sweep has 403 refined samples and reports target exceeded.
  These values are declared, not extracted from a PCB or inferred from part value.
- AC: actual explicit cross-section field solve, 20 mm conductor length,
  two 2 mm × 70 µm strips at y=0 and −0.8 mm, balanced ±current,
  12 V DC rail, 5 A DC plus 1 A RMS at 100 kHz, copper 20 °C.
  Total copper loss 0.1281256 W and loop AC drop 6.49113 mV RMS.
  The un-applied quick recipe in Setup is editable and separate from the
  detailed conductor table used here. No saved-board return extraction,
  dielectric loss or converter/control-loop simulation is claimed.

## Existing image inventory

The source inventory at base revision `d99f4602` covered 24 plugin directories
and 129 existing help/example PNGs. Size, colour variation, metadata and alpha
were checked. This is an asset audit, not proof that every workflow passed.
All earlier media was retained. The following table records the existing image
counts; current captures above are additions.

| Plugin | Existing PNGs |
|---|---:|
| bom_studio_plugin | 6 |
| bulk_label_editor_plugin | 1 |
| component_arranger_plugin | 2 |
| copper_balancer_plugin | 2 |
| embed_3d_plugin | 1 |
| extract_pins_plugin | 4 |
| fanout_generator_plugin | 10 |
| harness_workbench_plugin | 2 |
| heater_designer_plugin | 1 |
| layer_counter_plugin | 2 |
| manufacturing_readiness_plugin | 1 |
| mechanical_check_plugin | 5 |
| planar_magnetics_plugin | 11 |
| project_fusion_plugin | 2 |
| protocol_constraint_composer_plugin | 6 |
| quick_pi_plugin | 23 |
| quick_therm_plugin | 15 |
| signal_integrity_advisor_plugin | 9 |
| silkscreen_label_plugin | 8 |
| suite_assistant_plugin | 4 |
| trace_impedance_plugin | 5 |
| trace_refiner_plugin | 6 |
| variant_manager_plugin | 1 |
| via_stitching_plugin | 2 |

Seven older PNGs contain transparency. Current SI neighbours now uses a new
opaque capture. PI inspector/loss views now also have opaque current captures; the older
unused Therm board workspace remains historic rather than flattening transparent
pixels. Three silkscreen examples are already labelled offscreen native preview
rasters, not desktop screenshots; that distinction is retained.

Additional native setup captures were checked for Fanout, Via Stitching,
Heater, Magnetics, Harness, Manufacturing Readiness, Extract Pins and Constraint
Studio. Empty initial tables or unfinished async previews were not promoted as
updated result evidence. A final fresh-process Heater capture after button sizing
fixes has readable controls and was promoted: 80 × 50 mm serpentine, 0.5 mm
trace/gap, 35 µm copper, 12 V, 99 segments, 3.940 Ω, 3.05 A and 36.55 W.
No board apply or thermal simulation was performed. Extract Pins option rows
are improved, but selection-basket actions still appear hidden at this test size;
its empty setup capture stays scratch. This is not a suite-wide UI pass.
Existing populated examples remain in their READMEs.
