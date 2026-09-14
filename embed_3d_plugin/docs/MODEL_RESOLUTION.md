> **0.4.0 navigation:** the new default is the unified component window documented in `UNIFIED_WORKSPACE.md`. This document retains the earlier backend/advanced workflows; their separate dialogs are under **Options → Standalone library / live-board tools…**. See `TEST_REPORT.md` for current validation.

# Standard KiCad models and missing-link repair — 0.2.0

The 0.1.1 resolver relied on the saved JSON configuration, process environment and a limited installation-directory guess. That misses default/live KiCad variables which are not represented in those places. It also searched project/footprint-relative locations but omitted KiCad's stock-model-root fallback. These are defects fixed in 0.2.0. A screenshot showing only basenames cannot establish which defect, missing file, stale variable or ambiguous path affects an individual user's footprint.

## What changed

On KiCad's GUI thread, `NativeBridge.prepare_resolver` now snapshots the public `pcbnew.ExpandEnvVarSubstitutions` result against the current project. Standard model and footprint roots, variables used in model references and library-table URIs, and applicable whole-reference expansions are captured. The worker receives only ordinary Python strings/dictionaries; it never calls pcbnew from a worker thread.

Both `KICAD10_3DMODEL_DIR` and `KICAD10_FOOTPRINT_DIR` receive fallback installation-root discovery. This includes the running KiCad/Python installation ancestors and standard Windows, macOS, Linux and `/app/share/kicad` locations. Undefined old-version model/footprint variables fall back to their current-version equivalents; an explicitly defined old-version variable is not silently replaced. An undefined `KISYS3DMOD` can fall back to the current model root. Explicit user session variables take priority over native snapshots.

A link such as `Resistor_SMD.3dshapes/R_0402_1005Metric.step` is also checked relative to the stock model root. A faulty URI in one footprint-library table entry no longer prevents other entries from being read. Multiple existing, different relative-path candidates are still deliberately reported as ambiguous rather than silently choosing a potentially wrong model.

There is no component-category whitelist. Resistors, capacitors, inductors, connectors, IC packages and custom parts use the same resolver and byte-preserving embedder. Their actual linked files must exist locally. Installing a footprint library does not itself prove that every associated 3D file is present.

## User controls

**Models folder…** selects the root containing folders such as `Resistor_SMD.3dshapes` and `Capacitor_SMD.3dshapes`. This is a session setting, not a change to KiCad's global Configure Paths. Typical Windows installations use a root under the KiCad installation's `share/kicad/3dmodels`; the running program's real path is preferred over assuming a fixed drive.

**Find missing…** scans a chosen stock/custom root in a background thread for *exact basenames*. A unique candidate is proposed but is not applied until the user presses **Use checked matches**. Multiple candidates require a choice. This is an explicit repair, not proof that the candidate geometry is identical. The search is capped at 150,000 files, does not follow directory symlinks, supports cancellation, and does not download anything. Missing payloads inside a damaged embedded footprint require **Locate model…** and the original bytes rather than an external-link search.

**Locate model…** chooses one exact file. The user may also apply it to other entries with the identical original reference *and footprint-library context*. Matching only a basename across arbitrary libraries is not used for that bulk operation.

The table now includes **Details / reason**. Selecting a row shows the complete original reference, resolved path, transforms and error. **More → Save scan diagnostics…** writes the scan manifest and relevant stock-path information. It intentionally does not dump the process environment or unrelated credentials. The report contains local paths and should be reviewed before sharing.

## No implicit geometry substitutions

No WRL→STEP substitution, part-size substitution, suffix guessing, recursive basename auto-selection or automatic model download occurs. A compressed model can be embedded when the original link points to it or the user explicitly selects it. Its loadability is determined by the installed KiCad build, not by this plugin. External texture/Inline/assembly dependencies remain subject to the original embedder's limitations.

When a linked file is genuinely absent, the plugin cannot manufacture its original geometry. Install the matching model package or explicitly point to the intended local file. Use the error column/diagnostics to distinguish that situation from a variable or search-root failure.

## Primary-source references

Reviewed 9 September 2026. The source is the KiCad 10.0 branch, not a claim of testing every patch build.

- KiCad 10 paths and variables: https://docs.kicad.org/10.0/en/kicad/kicad.html
- Native resolver, including project/working/stock-root lookup: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/common/filename_resolver.cpp
- KiCad 10 Python namespace, `ExpandEnvVarSubstitutions`: https://docs.kicad.org/doxygen-python-10.0/namespacepcbnew.html
- PCB model and embedded-file workflow: https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html

The public native function was verified in the API documentation/source. Native execution remains untested in this build environment; see `TEST_REPORT.md`.
