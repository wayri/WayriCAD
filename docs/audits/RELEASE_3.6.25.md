# WayriCAD 3.6.25 release validation

This release updates the 17 IPC packages to 3.6.25 and Trace Refiner to 0.3.0.
Component Arranger, Layer Counter, Project Fusion, Variant Manager and
Silkscreen Label Placer retain their prior native versions.

## Validation status

### Trace Refiner native behavior

- Windows, KiCad 10.0.6, Python 3.11.5: 83/83 native tests passed in 228.280 seconds.
- In the reviewed repair fixture, the exact `track_not_centered_on_via` finding
  changed from one baseline finding to zero candidate findings. The gate requires
  the exact reviewed track/via contact and rejects unrelated errors.
- Candidate validation preserved copied project/custom rules. Repeated tuning
  chains remain protected, and exact undo/redo and stale-source checks passed.
- Running the extracted 0.3.0 PCM payload's native centering tests passed 21/21.
- Independent safety review found no remaining actionable issue.

### Shared and packaging checks

- Root suite: 494 passed, 88 skipped, 227 subtests passed.
- `validate_packages.py`: all 23 independent PCM ZIPs passed schemas, payload,
  runtime, action, icon and syntax checks.
- `validate_docs.py`: source-only and full ZIP image/document checks passed.
- Built the 3.6.25 wheel and sdist. The isolated wheel smoke passed; the sdist
  contains the release notes, this audit and both linked silkscreen audit files.
- Component Arranger, Layer Counter, Project Fusion, Variant Manager and
  Silkscreen Label Placer ZIPs are byte-identical to the verified 3.6.24 assets.

Exact-source CI, asset upload and public download hash verification remain
release gates. This audit is not publication approval.

Publishing assets and promoting the PCM feed are separate maintainer actions.
