# Connector-edge fanout and readable dropdown validation

Date: 2026-10-14. Windows, installed KiCad 10.0 bundled Python 3.11/wxPython; source regression checks also used Python 3.14.

## Changes

Long-name selectors in Quick PI, Quick SI, QuickTherm, Trace RLC, Extract Pins, Harness, Fanout and Via Stitching use the shared native choice wrapper. Windows popup width is measured from complete labels and bounded by the display; selected and editable values retain full tooltips. Item identity and indices are unchanged. Other wx ports retain native popup width and full-value tips.

Connector edge routes independent SMD/PTH pins to an extended courtyard/body envelope, with local exit sides and intersecting pin/net/scope filters. A bounded grid search preserves existing copper and checks obstacles. Non-plated holes remain obstacles. Layer-spanning PTH pins do not need source vias. Optional lower clearance is exported to a separate review project with an enclosed rule area and selected-net/layer scope. Live Apply refuses such plans; fabrication floors and existing higher-priority rules remain. JSON plans include the geometry, exception region and saved-rule fingerprint.

## Evidence

- A synthetic 78-pin staggered four-row plated connector with two non-plated mounting holes accepted all 78 escapes, with zero planner rejections, in 9.05 seconds (0.2 mm traces, 0.15 mm configured clearance, 0.25 mm grid; illustrative assumptions).
- Native DRC on that 78-pin routed fixture found no clearance, short or hole violations and no unconnected items. Its 78 dangling-track warnings are expected for deliberate open escape endpoints; the baseline had zero violations.
- Seven native connector geometry checks: all PTH pins escape, source unchanged, pin/net filters intersect, bottom-layer connection, rotated local exit, NPTH exclusion and connected-pin rejection (some checks share a case).
- Seven native/text review-export checks, including native KiCad CLI DRC: a 0.2 mm copper gap inside the area passes a 0.15 mm exception; the identical outside gap still violates its 0.3 mm default. Source PCB/project/rule bytes and live geometry/filename remain unchanged. Stricter unsaved fabrication floor is retained.
- Two native GUI checks: six-pin Preview/Apply/Undo/Redo, and local-rule preview disabling live Apply. Registration is mocked in the standalone wx test because it is outside PCB Editor; routing and board objects are native.
- Four native readable-choice checks cover measured Windows popup width, complete selected/typed value tips, item replacement and identity.
- Existing native routing suites: 21 advanced fanout, 8 group, 11 adaptive, 17 routing behavior, 23 layer routing, 9 perimeter expansion tests passed.
- Root pytest: 425 passed and 86 skipped initially; one modeless-editor source check failed after adding a file picker in the main module. The picker was moved to the shared UI helper; all 11 suite-UX checks and 68 subtests passed afterward. Native-skipped cases were exercised separately as listed above.
- All 19 disposable PCM archives passed official schemas, icons, syntax and independent runtime validation. Eight affected archives passed isolated native plugin/shared-runtime imports with source paths excluded. No published archive was replaced.
- Source documentation links/images and diff formatting checked. The connector README/offline help contain workflow and limits.

## Screenshot provenance and limitations

`fanout_generator_plugin/help-connector.png` is a real standalone native wx window on a disposable six-pin connector fixture. Captured through the window handle after layout/paint; no source paths or private project data are displayed. Numerical geometry was not redacted or altered.

The pictured user D-sub board was not available as a native fixture. Dense connectors may need a different layer, exit side, grid step or narrower scope; rejected pins remain explicit. Connector mode is not paired-channel routing or complete autorouting. Existing custom rules can override the exception, so exported projects require native DRC and review. macOS/Linux popup behavior and live editor IPC workflows were not visually validated in this change.
