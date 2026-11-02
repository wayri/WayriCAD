# Report formats and recorded path scope

Windows, Python 3.14.2; source follow-up to the saved-field gradient patch.
No release, PCM feed, installed plugin directory or board was changed.

## Supported behavior

Quick PI, QuickTherm and Quick SI report dialogs offer HTML and PDF. PI return,
AC, electrothermal, 3D and batch exports use the same choices. EMerge retains
its existing HTML/PDF controls. PDF exports retain companion HTML and complete
numerical JSON; supported portable result files remain available. Batch PDFs
include completed child reports, not only the comparison index. 3D PDFs include
static projections of the same bounded saved display samples, explicitly
distinguished from complete numerical cells in JSON.

PDF rendering occurs before recoverable publication of the report set. Tests
exercise rendering failure, publication rollback, source/output alias rejection,
format selection, cancellation and confirmation for existing companion files.
Managed PI/Therm/SI runtimes request ReportLab. HTML remains available without
executing the PDF renderer.

Recorded net names and directed paths precede plots and tables. Grouped endpoints
list every recorded reference.pin number; descriptive labels do not hide explicit
pin numbers. Series-stage tables retain order, models and both pin groups.
Aggregate plots retain their combined scope rather than claiming per-branch
solutions. SI routes, thermal source nets, reviewed power-tree edges and EMerge
signal/reference ports use stored evidence; missing PCB pin identities stay
Unknown. Source paths are shown in full as recorded, without resolving them or
inferring connectivity from names.

## Validation

- Complete shared pytest gate: **959 passed, 161 skipped, 518 subtests passed**.
  Includes all candidate PCM schema/independent registration checks.
- PI report, capacity, gradient, 3D, batch, AC and electrothermal workflow tests:
  **50 passed, 1 skipped, 27 subtests passed**.
- Complete thermal suite: **280 passed, 29 skipped, 221 subtests passed**.
- SI and EMerge suites together with importlib test collection:
  **467 passed, 79 skipped, 347 subtests passed**; two existing package-import
  deprecation warnings.
- New formats/context and existing portable-report checks:
  **49 passed, 4 subtests passed** before the additional descriptive-pin test;
  the final shared gate includes that test.
- Synthetic grouped-series export produced an 11-page PDF with eight embedded
  static figures. Text extraction verified both series pin groups and the full
  generic source path. Poppler rendered pages for visual inspection. Headless
  Chrome rendered the same HTML; inspection caught and corrected inherited
  two-column styles on the new scope sections. Final HTML uses full-width scope
  headings and tables. The synthetic all-layer view is explicitly projected.
- Source compilation, source documentation validation and whitespace checks
  passed. The earlier gradient-only commit passed the complete remote CI matrix;
  this follow-up needs its own CI run.

An initial shared run hit the Windows inherited-stdin handle issue; rerunning
pytest in a child with `stdin=DEVNULL` allowed the complete gate to execute.
The default interpreter uses the existing task-local jsonschema dependency.
An initial 3D refactor changed ordinary JSON formatting; the original compact
serialization was restored and its byte-for-byte contract test passed.

No native KiCad editor-window interaction was performed because the desktop was
reserved for other work. KiCad 10/11 installed-dialog acceptance remains pending.
Static PDF retains text, tables and embedded raster figures; interactive canvas,
SVG and unsupported views are explicitly retained in the accompanying HTML.
Existing renderer size/layout limits remain enforced. No circuit or solver
behavior was changed. Task-owned synthetic reports, rendered pages and browser
profile remain under `.validation/report-formats/`; no shared cleanup occurred.
