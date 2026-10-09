# Mechanical inspection validation — 3.6.13 candidate

Validated on Windows on 2026-10-09, with engineering-ruler and native workspace follow-up on 2026-10-10. The current source candidate advances all 17 IPC packages to 3.6.13 because they carry the shared launcher fix; Fusion and Variant Manager retain their published versions. The public PCM feed and published 3.6.12 assets were preserved.

## Behavior and evidence boundaries

Exact 3D part queries use Open CASCADE distances and closest-surface witnesses from transformed STEP solids. The live session stores private BREP copies from the completed analysis, checks the source board/model/enclosure fingerprints before and after queries, and strips its session token from portable reports. Changing analysis input or clearing pending measurements invalidates obsolete callbacks. Closing a session cancels its worker without blocking the GUI on the kernel.

Quick 2D distances are between same-side axis-aligned footprint envelopes. Saved Edge.Cuts contours provide unfilled visual context only; concavity, hole loops and native arc tessellation are retained. Missing/open outlines remain unavailable. Neither outlines nor PCB bodies participate as components in the automatic nearest-part search.

Point rulers measure Euclidean distances between picked tessellated surface points. They are stored separately from minimum part gaps and never establish nearest-part evidence. Zero surface distance alone does not establish positive penetration volume. Failed kernel checks remain unknown and prevent a nearest-part claim when they could hide a closer candidate.

## Earlier inspection checks — 2026-10-09

| Check | Observed result |
|---|---|
| Complete Mechanical Check suite under KiCad Python | 57 passed in 47.394 s; no skips |
| Shared repository suite under Python 3.14.2 | 397 passed, 73 skipped, 152 subtests passed in 53.80 s |
| Candidate PCM build and validation | 19 independent ZIPs; official schemas, action manifests, icons, vendored runtime and Python syntax validated |
| Final report diagnostics and behavior | Focused Node/Python report tests passed after the final ruler-label and missing-evidence text updates |
| Native source window | Saved-board run, typed part pair, numerical envelope reference, actual ray picks, point ruler, nearest hover, GPU rendering, export, stale-callback rejection and clean close passed |
| Extracted Mechanical PCM window | Same native workflow passed in Quick 2D and with actual 3D STEP solids, with code and shared runtime loaded exclusively from the extracted plugin; exact J1/C3 gap 28.638274058 mm, separate picked-point ruler and nearest hover verified |
| Extracted Mechanical PCM exact pipeline | Four modelled components; uncached C2/J1 query returned 13.320688458 mm with exact STEP witnesses; repeated cached query matched; source hash unchanged |
| Final offline report in the in-app browser | Board outline, reference labels, separate gap/point labels, saved H1/C2 distance and actionable missing-pair result verified; no browser console errors observed |

The native runtime was KiCad 10.0.6, Python 3.11.5, wxPython 4.2.2 / wxWidgets 3.3.2, PyOpenGL 3.1.10 and FreeCAD 1.1.3. Native tests include rotated asymmetric/bottom-side models, exact interboard findings, contact versus positive-volume intersection, independent XY/Z diagonal clearance, source immutability, missing geometry, cancellation and cache lifecycle. Outline tests use actual KiCad segments, arcs/circles, a concave contour, circular cutouts and invalid outlines.

The first restricted shared-suite run failed on Windows sandbox temporary-file permissions. The recorded passing run used a workspace-local temporary directory and normal runtime access. Skips in the shared suite cover unavailable optional/native integrations; they are not passes. Linux/macOS native windows and KiCad 11 extraction were not verified by this candidate.

## Performance reference

For 80 actual FreeCAD box solids, the all-pairs reference made 3,160 unique distance calls. The indexed nearest-part results matched that reference for every part, including Euclidean witness distance within numerical tolerance.

| Fixture | Exact distance calls | Cache hits | Indexed search | All-pairs reference |
|---|---:|---:|---:|---:|
| Spaced boxes | 64 | 32 | 0.266 s | 12.064 s |
| Coincident boxes | 79 | 1 | 0.534 s | 22.559 s |

These timings measure the nearest search only, excluding import, STEP export, full collision coverage and tessellation. The dense zero-gap case can stop its nearest search immediately; full collision screening must still inspect all potentially colliding pairs. Performance depends on geometry and arrangement.

Native indexed picking matched brute-force ray hits on a 6,400-triangle fixture with fewer than 30 triangle tests per sampled ray. The offline index used nine triangle tests for a 20,000-triangle fixture. Section clipping retains a valid back surface when the front surface is clipped away. Native GPU buffers and offline WebGL buffers are reused across frames and released when their scene is replaced or closed.

## Engineering rulers and workspace — 2026-10-10

Review uses a resizable viewport/sidebar split. The toolbar identifies Quick 2D envelopes or exact STEP solids and offers Load 3D models / 3D view. The final native canvas occupied 856 × 608 pixels in an 1184 × 781 pixel client window. Grid and substrate transparency start off. Only active/hovered rulers and selected/hovered references receive ordinary labels; historical witness lines remain. Deterministic label placement reserves the scale bar, stays inside the viewport and omits crowded labels.

Exact CAD edge-to-edge and point-to-edge queries resolve stored BREP edge indices and use the kernel's distance and witness points. Curve samples identify edges in the viewer, never drive the numerical distance. Sampling is bounded to 100,000 scene points and at most 65 points per curved edge; unavailable display samples are explicit, while numbered edges remain queryable. Same-body edges, circles and B-splines are covered by numerical tests.

Body-center rulers use geometric volume centroids of the transformed constituent solids with uniform volume weighting. Density is absent; these are not mass centers. The click-to-open part card shows assembly-axis-aligned CAD XYZ extents/ranges, volume, centroid and edge count. The extents are not an oriented bounding box or manufacturing dimension drawing. Picked surface points remain tessellation approximations. Feature rulers have separate report/cache records and never establish minimum gap, collision or nearest-part evidence.

Validation before the height/proximity follow-up: the full Mechanical suite passed 85 tests with no skips in 114.001 seconds, followed by 8 focused feature tests after final imported-record/coordinate validation changes. Analytical checks included line/circle/B-spline distances, rotated/asymmetric compound centroids, exact-at-contact distances, source/cache mutation before and after a worker, cancellation, close, immutable cached results and imported evidence replay. Both native source views passed actual ray-pick, camera drag, nonoverlapping-label, opaque-export and unchanged-source checks. The extracted independent Mechanical PCM passed exact 3D with all feature tools, real CAD-edge picking and the actual dimension popup. Nineteen disposable PCM ZIPs passed package/schema/runtime/icon/syntax validation. These checks were rerun as needed for the height/proximity additions recorded below.

## Global height and proximity follow-up — 2026-10-10

Global maximum heights now check both outward PCB faces for every primary component solid: top `max(0, zmax − thickness)`, bottom `max(0, −zmin)`. Mounting side does not suppress opposite-side protrusions. Separate side identities, measured height, limit, excess and 1e-7 mm comparison tolerance are exported. CAD bounds can conservatively enclose curved geometry; height markers locate that envelope rather than claiming a closest-surface witness. Missing models and Quick 2D do not establish height. Regional zones keep their existing policy.

The optional `proximity_warning_mm` defaults to zero for legacy rules. Its broad-phase margin preserves all primary component pairs within the warning distance; exact STEP surface gaps generate warnings only after collision/hard-clearance precedence. Quick 2D warnings retain same-side footprint-envelope evidence. Warning records and height markers stay separate from nearest-part and feature-ruler caches. Comparison-board/enclosure checks retain their existing clearance rules. CSV includes side and excess, while JSON/HTML preserve full evidence. Waived findings remain recorded without active violation colors.

| Final source check | Observed result |
|---|---|
| Full Mechanical Check suite | 94 passed, no skips, 96.048 seconds under KiCad Python after the final live waiver-marker refresh fix |
| Height/proximity references | Six focused tests passed, including imported STEP box geometry, both-face/opposite-side protrusion, exact threshold, soft-gap boundary, disabled warnings, collision/hard-clearance precedence and CSV fields |
| Native exact 3D capture | 856 × 608 canvas, seven solid bodies, two real ray picks, four feature queries, five nonoverlapping labels, two height violations and four proximity warnings; GL error zero; source unchanged; applying/removing a waiver refreshes markers without discarding the active ruler |
| Native Quick 2D capture | Six footprint envelopes, three nonoverlapping labels, seven proximity warnings and no claimed heights; source unchanged |
| Offline report behavior | Node/Python checks passed in the full suite: both-side labels, warning/error color precedence, waiver exclusion, marker visibility, preserved nearest-gap evidence and bounded collision-free labels |
| Final independent Mechanical PCM | Extracted plugin/runtime imports, actual STEP 3D tools, height/proximity labels, automatic dimensions, applying/removing a waiver and unchanged source passed |
| Candidate packaging | 19 independent PCM ZIPs validated; source docs and packaged Mechanical help/README images validated; wheel built and isolated CLI/assets/API/numerical smoke passed with synthetic example data |

The pictured exact fixture reports J1 top excess 6.535 mm above a 2 mm allowance and bottom excess 1.355 mm above a 0.05 mm allowance. Its 20 mm proximity warning threshold deliberately demonstrates warning markers; these settings are illustrative rather than mechanical acceptance criteria.

The wheel smoke needed normal localhost access after the sandbox denied its loopback connection (Windows error 10013). It uses bundled synthetic BoM and simulation examples, not a user board or an external service. Final native checks use Windows/KiCad 10.0.6 and FreeCAD 1.1.3; they do not establish a live PCB Editor workflow on other machines. The shared root suite/performance timings above are earlier evidence rather than a new full-repository run.

## Screenshot provenance and limitations

`mechanical_check_plugin/help-workflow.png`, `help-quick2d.png`, `help-measurements.png` and `help-part-dimensions.png`, with their packaged resource copies, show the repository's synthetic saved-board fixture in actual native windows. The 3D measurement image comes directly from the OpenGL RGB front buffer with no GL errors; the workspace images capture the bounded visible native client area. The non-GL popup capture renders its own native children. None contains a personal path, private board or network address; no redaction, image editing or retouching was applied. The fixture deliberately has findings and missing coverage; its images are not passed mechanical audits. Quick 2D outlines are visual context rather than substrate solids; the exact 3D image uses actual exported STEP substrate and component solids.

The reproducible native check is `python tools/check_mechanical_workspace.py --mode exact3d --output-dir <local-output>` using KiCad Python. Use `--mode quick2d` for footprint envelopes and `--package-root <extracted-PCM>/plugins` for independent-package checks. The tool checks source immutability, numerical and ray-pick behavior, viewport size, UI tools, labels and exported pixels; it uses a synthetic saved board, not a live editor connection.

Exact analysis still requires usable models and FreeCAD; missing coverage remains incomplete. Static geometry does not establish assembly motion, tolerance stacks or manufacturing acceptance. Offline reports can show saved part/feature measurements and add point rulers; an uncached exact query requires a new native analysis. Snapshot hover witnesses do not automatically update after external design changes. The 2026-10-10 additions do not establish Linux/macOS native GUI or KiCad 11 compatibility, and no new browser visual run is claimed for them.
