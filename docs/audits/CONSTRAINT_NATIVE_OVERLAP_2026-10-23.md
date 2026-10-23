# Constraint Studio and native KiCad — 23 October 2026

Constraint Studio now concentrates on grouped rule generation and reviewed
project changes. Ordinary rule, netclass and Board Setup editing belongs in
KiCad. These changes are newer than the published 3.6.28 binaries.

## Scope

| Feature | Current ownership |
|---|---|
| Individual rule creation, editing, copying, deletion and priority | KiCad Tools → Design Rule Editor; Studio displays rules read-only. |
| General condition builder and min/preferred/max cell editing | Removed from Studio's visual and native interfaces. |
| Netclasses, assignment patterns and generic board-setting editor | KiCad Board Setup; duplicate Studio pages removed. |
| Protocol presets, pairwise clearance matrices and reusable sets | Retained as grouped composition workflows. |
| BGA managed regions and scoped layer/via profiles | Retained; no claim that these are a replacement for native routing or tuning. |
| Scope inspection, source fingerprints, review export and offline apply | Retained. Existing native rule syntax and unknown clauses remain preserved. |

The boundary follows the KiCad 10 manual's
[graphical rule editor](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#graphical-design-rule-editor)
and [design-rule configuration](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#configuring-design-rules).
The layered profile workflow remains useful for protocol instances, exact net
groups and via recipes; ordinary single-rule editing is handed back to KiCad.

Removed bridge operations are rejected before touching workspace state. The
native fallback no longer constructs the old rule dialogs, netclass page or
board-settings page. Its overview cells are read-only, with scope/details panels
closed initially. Parsing, generation and transaction code remains available for
preserving existing files and the retained generators.

## Executed checks

Windows, KiCad 10.0.6, bundled Python 3.11.5, wxPython 4.2.2 / wxWidgets 3.3.2:

- 382 plugin regressions passed, including the dependency-free browser overview
  and stale-action checks.
- 27 native wx bridge/lifecycle, saved-source refresh and review tests passed.
- Actual WebView workflow passed: read-only overview, rejected old edit without
  mutation, matrix staging, Undo/Redo, set/routing/review pages and native help
  recovery. No JavaScript errors were recorded.
- Actual native window passed: removed pages absent, overview not editable,
  removed bridge commands rejected, protocol generation and review-bundle
  export working. All public fixture source files remained byte-identical.
- Native KiCad DRC processed the exported fixture and reported violations
  (exit 5), with inputs unchanged and no parsing error. This is an exercised
  validation path, **not a clean DRC result**.
- Offline help retains 101 topic IDs, including 34 constraint and 27 function
  reference entries. General authoring instructions now point to KiCad.

The Playwright-based full browser harness was updated but not run because its
dependency was unavailable. The actual native WebView workflow above was run
separately; no cross-platform or installed-PCM acceptance is claimed.

## Screenshot

![Current native read-only overview](../../protocol_constraint_composer_plugin/help-readonly-overview.png)

Actual native fallback window on the public `workflow_demo.kicad_pcb` fixture,
after staging illustrative USB2 rules. Table values are demonstration inputs,
not approved fabrication dimensions or evidence that the fixture passes DRC.
The captured client area is 1452 × 803 pixels, opaque RGB with empty PNG metadata.
Headers and controls were visually inspected; no private paths or identifiers
were present and no redaction was needed. Earlier screenshots remain labelled
as historical editable interfaces.

SHA-256: `980bb70b361f99e6cb82e037339d035f5a25b0216f7a73d9d9f0bf04a6c7f5dc`.
