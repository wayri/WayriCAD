# Routing plugin README screenshot provenance — 2026-10-23

These are genuine native application captures. No application geometry, result
text or status was drawn over the images. Existing illustrations were retained.
This documentation update does not rebuild or replace released binaries.

## Environment and scope

- Windows; KiCad 10.0.6; its bundled Python 3.11.5.
- wxPython 4.2.2 (MSW Phoenix), wxWidgets 3.3.2.
- Source revision at capture: `bb1caf53bd0ef7739460b70e8ef61df3b35d871e`.
- Standalone native source windows, using disposable synthetic boards. This is
  distinct from a PCM-installed action connected to a running PCB Editor.
- No original/private project was opened or modified. Capture headers, status
  text and PNG metadata were checked for private paths and personal details.
  No redaction was needed. The four new images capture client areas, preserving
  their aspect ratio and all primary action buttons.

## Trace Refiner: validated comparison and explicit Apply

| Image | What it shows |
|---|---|
| [Validated comparison](../../trace_refiner_plugin/help-validated-comparison.png) | Native Side by side view: amber original, teal proposal, proposal metrics and successful validation status |
| [Applied refinement](../../trace_refiner_plugin/help-applied-refinement.png) | Actual Apply status, cleared proposal table and enabled Undo; both panes now display current board context |

The disposable two-pad `SIGNAL` fixture uses five 0.20 mm-wide F.Cu segments
with 0.15 mm local jogs. Scope is Whole board; maximum displacement is 0.20 mm;
maximum shortening per chain is 0.30 mm. The planner proposed one replacement
segment: 6.1243 mm before, 6.0000 mm after (0.1243 mm shorter).

The UI's **Validate candidate** ran the detached native worker and KiCad DRC.
It reported two baseline findings and two candidate findings, **zero new
findings**, and unchanged native terminal connectivity. This does not claim
zero total DRC findings. Preview/validation left native routing unchanged.

**Apply refinement** produced one native track and retained the first source
track's UUID. Native terminal connectivity remained unchanged. In-window Undo
restored the complete original track snapshot. The saved source file hash stayed
unchanged throughout: `2488d4259a824e3410f722cf68f3f3e9420a607c6c952f33b8e9de2f66c2b53f`.
Both UUID setter APIs are callable in this installed runtime; this capture alone
does not prove the setter-free fallback on another KiCad installation.

The separate [native UUID compatibility suite](../../trace_refiner_plugin/tests/test_uuid_compatibility.py)
also passed **4 tests in 120.331 seconds**. It exercised available setter paths,
a setter-free native clone proxy, UUID preservation through validation and
Apply/Undo/Redo, and rejection of broken setters or conflicting replacement IDs
before writes. This targeted test evidence is separate from the screenshots.

## Fanout Generator: existing copper and accepted proposal

| Image | What it shows |
|---|---|
| [Before](../../fanout_generator_plugin/help-connector-before.png) | Main canvas: six existing PTH pads and courtyard, without proposed copper |
| [After](../../fanout_generator_plugin/help-connector-proposed.png) | Main canvas: six accepted teal connector escapes, zero rejections |

The style thumbnail continues to show the accepted proposal in both views.
The captures use a disposable six-pin plated connector, explicit `J1` reference
scope, Connector edge / Nearest edge and no endpoint vias. The planner reads a
private saved-board snapshot. The views are presentation modes, not separate
plans; no copper was added while capturing either image.

Explicit Apply then added 12 track segments to the in-memory fixture. In-window
Undo restored its original empty routing. The saved source hash remained
`6f79c74231e1ac8954319290f8885a5dd770c1b5fd01549ccb94dade036699c6`.
No native DRC signoff or real connector/fabrication qualification is claimed for
this example. A native focus warning appeared in the capture log; both images
were inspected and the preview, Apply and Undo checks completed successfully.

## Via Stitching: retained signal-guard example

[Guard preview](../../via_stitching_plugin/help-guard-preview.png) is the existing
native Windows / KiCad 10.0.6 capture. It was visually inspected and retained,
not newly recaptured in this documentation pass. It shows a synthetic two-layer
filled-ground board, exact `SIGNAL` selection, both guard sides, 3 mm pitch,
1 mm centre offset and **22 prepared GND through-vias**. It shows unattached
preview geometry, not evidence that those vias were committed. Coverage on at
least one filled target layer does not establish an RF return path or shielding
performance. Existing grid illustrations also remain in the README.

## Image integrity

| File | SHA-256 |
|---|---|
| `trace_refiner_plugin/help-validated-comparison.png` | `3ba7e423728f72652db609e9886b5737b25719ec076e00d12b857bded5496af3` |
| `trace_refiner_plugin/help-applied-refinement.png` | `bcf1a2f1740e74e7837d87d26f726b4211903e328cbcea2e5f217151a0127063` |
| `fanout_generator_plugin/help-connector-before.png` | `ea9b83500b7453c57a16ad23b11620214cb3f2cdcf40e1d112aa944c7116c6f4` |
| `fanout_generator_plugin/help-connector-proposed.png` | `20094dd1d4155f1a50dfe96cdd089f8f16a2e635cb6c4e3d0b87b4342005f692` |
| `via_stitching_plugin/help-guard-preview.png` | `7cea16c00b03b9c09a8bb725143ed06cc762013bb7f31a0b63bf5b7f87155b1c` |

The four new PNGs and the retained Via image were inspected at native aspect
ratio. The capture/verification scripts and raw JSON remain local validation
artifacts; they contain temporary workspace paths and are not release assets.
All five images decode as opaque RGB with empty PNG metadata. The source-only
documentation/link/image validator passed after the README updates.
