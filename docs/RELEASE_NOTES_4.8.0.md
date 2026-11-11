# WayriCAD 4.8.0

This minor release updates the suite's 27 independent PCM packages and Python
distribution to 4.8.0. KiCad 10 remains the native baseline; newer-version and
platform support remains tool-specific. Scientific tools retain their testing
labels and require their documented optional/native runtimes.

## Trace RLC Protocol Discovery

- Bounded token/fuzzy matching plus user-defined wildcard/restricted-regex rules.
- RGMII, SGMII, DDR, PCI/PCIe, SerDes, GTH/GTY/GTX/GTP and the other documented
  USB, Ethernet, peripheral, display and RF naming families.
- Hierarchical/lane-scoped pair candidates, ambiguity and missing-mate review.
- Existing saved-copper section extraction checks supported single-ended
  impedance against explicit/nominal screening targets and suggests corrective
  directions. Missing references, possible stubs, vias and unsupported terms
  remain visible, not passing by default.
- Cancellable isolated native worker, sortable review window, HTML/JSON evidence
  with source fingerprints and UTC time, plus `protocol-profiles` / `protocols`
  CLI commands. Reports cannot overwrite rule inputs or use stale source files.

Automatic coupled differential impedance and full protocol compliance are not
solved. No bit rate is inferred from spelling and no PCB is automatically edited.
See the [protocol guide](../trace_impedance_plugin/PROTOCOL_SCANNING.md).

## QuickTherm Setup

- Known component power can be included explicitly without requiring thermal
  junction resistance for the board-temperature model.
- Ambient inputs accept explicit Celsius/Kelvin; zero-power entries are valid.
- Automatic model selection uses usable saved stackup data where present and
  keeps missing-stackup assumptions visible. Optional STEP handling is off by
  default; a missing junction model remains unknown rather than blocking a
  supported board screening result.

These starting assumptions are not material qualification or thermal sign-off.
Review power, cooling, geometry, mesh and omitted effects for each design.

## EMerge and Antenna Views

- Adapter support for EMerge 3.0.4 and emsutil 1.1.6, with exact-pair runtime
  qualification certificates, guarded candidate activation and rollback.
- Saved field/vector views, polarization and S-parameter inspection, denser
  research visualizations, AESA 3D array-factor lobes and beam steering.
- Paper-derived SIW/DRA and PCB horn reconstructions expose inferred dimensions
  and disagreements rather than claiming replication where evidence is absent.
- Actual solver data, analytical array-factor models and geometry-only previews
  retain separate labels and provenance.

The coarse 22-case adapter qualification checks compatibility, not mesh
convergence or physical accuracy. AESA steering is analytical array factor,
not a solved coupled array/feed network. Paper comparison failures and omitted
geometry remain documented. See [research evidence](../examples/quick_emerge/research_antennas/VALIDATION.md)
and [reconstruction assumptions](../examples/quick_emerge/research_antennas/PAPER_RECONSTRUCTIONS.md).

## Website and Guidance

The [product page](https://wayri.github.io/wayricad/) gains a searchable task-based
directory, installation feed, CLI/jobset workflows, screenshots, FAQs and model
limits. Search/share and structured software metadata identify one canonical
product. Repository/package homepages point there. Agent guidance now records
content ownership and distinguishes local, installed, published and deployed work.

## Verification and Known Issues

- Source checks and native probes are recorded in the
  [lifecycle/protocol audit](audits/PROTOCOL_SCAN_AND_NATIVE_LIFECYCLE_2026-11-11.md).
- The RLC protocol window/worker passed a KiCad 10.0.6 synthetic 12-net test;
  missing stackup/reference evidence did not produce false passes.
- Fifteen other audited source windows opened/closed successfully. These probes
  do not exercise every button, live-editor transaction or long-running solve.
- **Unresolved:** Constraint Studio source and installed versions reproducibly
  raise `GetRowPos(): invalid row index` in the audited Windows accessibility
  path. No reliable fix was demonstrated. Accessibility is not disabled and
  assertions are not suppressed. No native access-violation crash was reproduced
  in the completed bounded probes.
- Website source tests and desktop/mobile previews do not replace a real Jekyll
  build or successful Pages deployment. Search indexing/rankings are not promised.

The release-validation receipt records the actual candidate checks, skips,
package/import validation and uploaded asset hashes. Installation into a local
KiCad instance is separate and was not performed on the low-space system drive.
