# KiWay Manufacturing Readiness Manager 0.1.0

Combines fabricator capability profiles and release gating in one workbench. It audits track, clearance, drill, annular-ring, aspect-ratio, and layer-count limits; runs KiCad JSON DRC and `.kicad_jobset` workflows; blocks package generation on failed profile checks; and writes a release ZIP with a SHA-256 manifest.

Save the project before analysis. A passing profile check does not guarantee acceptance by a fabricator. Confirm stackup, impedance coupons, materials, tolerances, finishes, drill definitions and the active quotation separately.
