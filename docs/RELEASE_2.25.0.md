# KiWay v2.25.0 Release Notes

## Restored Plugin Entry Points

- Every KiWay package entry point (`__init__.py`) now uses guarded imports:
  plugins import cleanly outside KiCad, register normally inside PCB Editor,
  and never crash standalone tooling when `pcbnew` or `wx` are unavailable.
  This restores `kiway dependencies` suite health checks, the CLI control
  plane, and the full test suite on machines without a KiCad runtime.
- Repairs the Manufacturing Readiness Manager, PDN and Decoupling Planner,
  Signal Integrity Advisor, Heater Designer, Planar Magnetics Workbench,
  Protocol Constraint Composer, Return-Path Auditor, Bulk Label Editor,
  Fanout Generator, Via Stitching, Test Point Descriptor, Trace RLC Analyzer,
  and Kilo Localizer entry points.

## Interfaces and Automation

- `kiway capabilities`, `kiway run`, and `kiway serve --stdio` verified against
  all ten machine operations: `bulk-label.preview`, `harness.build`,
  `heater.analyze`, `magnetics.analyze`, `manufacturing.audit`,
  `pdn.analyze`, `protocol-constraints.compose`, `return-path.audit`,
  `signal-integrity.i2c-pullup`, and `test-point.fixture`.
- The PCM feed remains internally consistent: every current package download
  URL, SHA-256 digest, size, repository resources archive, and icon set is
  regenerated from source and validated before release.

## CI and Packaging

- The CI workflow again compiles the actual seventeen-package suite instead of
  retired packages (Connector ICD Builder, Net Hygiene, Test Coverage
  Planner).
- Fixture-generator tests skip only the `pcbnew` load step when running
  outside KiCad while still verifying board text generation deterministically.
- PCM feed consistency tests no longer pin an obsolete release tag; they
  derive the expected tag from `pcm/repo.json`.
- `install.bat` installs all seventeen current packages, skips absent folders,
  and no longer references removed plugins.

## Safety

No geometry, analysis, or write-path behavior changed in this release. All
mutating tools continue to require explicit preview confirmation before any
PCB modification.
