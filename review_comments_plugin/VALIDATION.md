# Review companion validation

## 4.4.0 release packaging

The new visual guide and local screenshots are included in the Review PCM ZIP,
wheel and source distribution. Archive validation, private candidate-feed and
packaged-document validation, and isolated wheel import/CLI smoke checks passed
on Windows. Packaging contracts passed **38 tests and 26 subtests**, with three
explicit native/viewer opt-in skips. Existing published assets and the public
feed were preserved during candidate preparation.

KiView stays externally supplied under its separate license. No viewer code is
bundled or relicensed. Package checks do not establish installed PCM GUI launch,
live OAuth approval or a connected KiCad 11 Review workflow. The full release
CI result is recorded with the public release rather than inferred from these
local checks.

Online KiView interoperability passed **nine cases**, using the actual online
client's `review-comments.js` through Node without copying it into this project.
Eight GitHub/GitLab × PCB/schematic × point/region annotations survived desktop
Markdown → online parser → online JSON export/sidecar parse → online Markdown →
desktop readback. Reference/net names, Unicode, coordinates, state, severity,
tags, mentions and update time were preserved. A changed commit or stale
snapshot did not authorize markers. This is local format interoperability,
not a new live-provider publication test.

Visible-window automatic refresh passed **46 focused hidden-wx tests** covering
inactive visible reads and response application, hidden/minimized pause,
single-flight requests, remote edits/deletions, stale-marker clearing, recovery
and draft retention. Authorization and session-identity checks remain in force
before and after provider work. An independent read-only lifecycle review found
no additional consequential gap; it did not perform live provider or UI tests.

## Embedded KiView source integration — 4 November 2026

### Dark-theme correction and compact workspace

Native Windows acceptance verified a single live light/dark toggle across the
schematic viewer, comment cards, search, composer and scroll rail. White native
scrollbar tracks and splitter separators were removed from the client area;
the operating-system title bar retains its Windows appearance. The empty draft
remained empty. Splitter dragging and scrolling to the final comment worked.
Hidden-scrollbar layout now retains the full height of offscreen
cards; a four-card regression reproduces the previous collapsed-card failure.
The external viewer's new `viewer-chrome.mjs` module is included in the bounded,
verified asset closure. Missing viewer errors remain visible after loading a
saved design instead of being overwritten with a success status.

`screenshots/review-dark.jpg` and `review-light.jpg` are unedited native-window
captures of the same public schematic, four illustrative markers and local-only
comments. These supersede `review-minimal-dark.png` and
`review-minimal-light.png` as appearance evidence. Native Windows title-bar
appearance is outside the per-window client palette. No live provider sign-in,
provider write or KiCad editor attachment is claimed by these captures.

Focused native checks after this correction: **37 passed** for conversation,
search and scroll controls; **14 passed** for search/scroll/workflow checks.
Asset closure checks against the current external source: **7 passed, one
Windows symlink-permission skip**; native web-host adapter tests **33 passed**.
Source documentation/link/image validation and `git diff --check` passed.
Earlier focused authentication checks covered
device-flow polling/cancellation, token expiry and session authority with mocked
transport, plus native dialog construction; real provider browser approval for
the new direct desktop OAuth flow remains unverified. These are source-window
checks; release archive checks are recorded above. KiView remains externally
supplied under its separate distribution license.

This source feature is not included in the published 4.3.0 assets. KiView is
loaded from an explicitly selected external asset directory; it has not been
vendored or independently packaged with Review. Release 4.4.0 retains this
externally supplied renderer boundary and does not assume a new license grant.

Windows native acceptance used KiCad 10's Python 3.11.5, wxPython 4.2.2 and the
Edge WebView2 backend. The actual Review window loaded the installed KiCad
`pic_programmer` sample PCB and paired schematic. It rendered copper, pads,
footprints, board outline and schematic symbols/wires. Clicking an illustrative
PCB marker focused its matching conversation; clicking the message location
centered the PCB camera. Switching PCB/schematic/3D and orbiting the 3D board
worked, with markers following the projected board positions. A point click
reached the native composer as an unpublished coordinate anchor. No provider
write or native-editor design edit was performed.

Focused host tests passed **30 cases**; the existing native conversation tests
passed **25 cases** separately. Document/asset tests passed **11 cases with two
skips** in the native runtime. These cover source/scope guards, bounded payloads,
catalog choices, stale callbacks and asset dependency closure. A combined native
suite attempt was interrupted by Windows bitmap/icon allocation failures and
an access violation; it is not a complete-suite pass. Native draft preview,
Linux/macOS, current installed ZIP launch, live editor cross-probing and live
provider publication through the new canvas remain separate checks.

The screenshots under `screenshots/` are actual unredacted window captures of
that sample, with a visible **DEMO — saved fixture · illustrative comments · no
provider or live editor connected** header. No personal paths or credentials
appear. `review-pcb.png` shows the full board with four illustrative anchors;
`review-schematic.png` shows the paired schematic; `review-3d.png` was captured
after an orbit gesture. 3D used zero linked component models and approximate
stand-ins, with that limit visible in the window. Custom worksheets and STEP
models are not supported by this integration. These captures supersede the
black images for demonstrating current source appearance; older files and
their audit below are retained as historical evidence.

## Published companion validation — 29 October 2026

Review is a testing package in WayriCAD 4.0.2. The checks below record the
review companion's tested scope; platform and provider limitations remain
explicit. Previously published release assets and tags are unchanged.

## Checks performed

| Check | Result and evidence boundary |
| --- | --- |
| Full shared suite | 867 passed, 130 skipped, 502 subtests passed on Windows / Python 3.14. Skips include unavailable native dependencies; they are not compatibility passes. Includes the Review inventory, help index and read-only Assistant source-inspection adapter. |
| Native Review regression suite | 239 passed using KiCad 10.0.6's Python 3.11.5 / wxPython 4.2.2. Includes guided setup, formatting, multiline/emoji selection, local preview, sanitized HTML paste, image-file queue/cancel, native drop routing, reply/draft preservation, bounded feed, actual login verification and source guards. Before the final focus regression, the combined native run including the project-result library passed 301 tests with one symlink-permission skip; mocked repair-policy checks are not live browser authorization. |
| GitHub Discussions backend | 51 focused GraphQL tests cover complete comment/reply pages, actual native-thread mutation inputs, scope/URL validation, partial-result rejection and ambiguous publication receipts. |
| Saved source identity | Git LF and Windows CRLF checkout equivalence accepted; any other content change rejected. Exact local SHA-256 protects subsequent operations. Public thermal-demo bytes unchanged after live tests. |
| GitHub live backend | Existing gh-authenticated account used. Real comment publication and anchor readback, provider edit/anchor removal, and provider deletion all reflected by fresh reads. |
| GitHub native pane | Native clipboard text pasted into the redesigned card-based pane, posted by its worker, then confirmed from the real provider response. Exact saved-board bytes unchanged. |
| Native image paste | Actual GitLab clipboard bitmap, PNG encoding, native preview, real upload and authenticated exact-byte download passed against the approved private issue. The image note and saved-revision marker were independently read back; the fixture SHA-256 was unchanged. The generated tile preview was approved programmatically. Multiple-file/drop/cancel checks use simulated transport; no operating-system drag gesture is claimed. |
| Formatted text | 55 pure helper cases cover Markdown edits, HTML clipboard conversion, inert preview, hostile content, bounds and unsafe links. The native suite checks toolbar formatting and Unicode offsets. |
| KiView interchange | Python-generated GitHub/GitLab markers accepted by KiView's JavaScript parser; its regenerated Markdown accepted back by Python. GitLab attachment receipt schema also tested. |
| PCM candidate | Official checked-in IPC/PCM schemas, ZIP integrity, local help/assets, vendored runtime and Python-member compilation checked. Isolated import checks are recorded with the final candidate package. |
| Documentation | Main catalogue and user guide include the candidate and its icon; source documentation/link/image validation run. |

The temporary [GitHub integration-test issue](https://github.com/wayri/WayriCAD/issues/32)
is closed. Its test comments were removed after verification. It used the public
`quick_therm_plugin/examples/thermal-demo.kicad_pcb`, not a private project.
No board or schematic writes were performed by the companion.

An initial clipboard test helper failed in Windows OLE clipboard restoration.
That helper was removed from the test path. The successful native run used
explicit text/bitmap snapshots and restored those clipboard formats; the
failure was not counted as a successful plugin test.

## Checks still unavailable

- **Browser approval boundary:** the official GitLab CLI browser flow completed,
  and a fresh API check succeeded both independently and in the native test.
  The plugin did not operate the browser or transfer credentials. The private
  native acceptance run posted exactly two labelled notes (text and image) and
  verified their actual provider readback. Its completed intent prevents duplicate
  sends. The image preview was approved programmatically for the generated tile;
  manual end-user approval and operating-system drag/drop remain unverified.
- **Running-editor navigation:** this task did not receive an originating
  editor IPC socket/token. Selection, rollback/focus and source checks have
  isolated test coverage; they are not a verified live PCB Editor launch.
  The native test interpreter also lacks `kipy`; the candidate declares its
  managed IPC dependency, but installed-runtime preparation was not exercised.
- **Schematic selection and transient overlays:** this adapter exposes no
  supported capability for them. It reports that limitation and never creates
  saved review shapes or fake ERC/DRC objects.
- **GitHub image attachment:** browser editor fallback is implemented; no
  undocumented attachment upload endpoint is used. A live browser-image upload
  was not performed by this companion task.
- **Live GitHub Discussion publication:** the repository reports Discussions
  enabled but has no existing topics. No public Discussion was created solely
  for this test. The separate adapter has GraphQL contract/regression coverage;
  a live native Discussion reply still needs an existing topic and explicit
  write-test authorization.
- **Cross-platform UI and appearance:** native checks/capture cover Windows
  light theme. Linux, macOS, dark-theme interaction and installed PCM launch
  remain unverified. CI registration does not establish those host checks.

## Screenshot provenance

**Image audit — 4 November 2026:** `help-workflow.png` and
`help-composer.png` are 1120 × 919 RGB files containing only black pixels.
They are unusable captures and have been removed from the README presentation,
with the files retained for provenance. `help-discussions.png` (1120 × 919)
and `help-setup.png` (760 × 660) were visually inspected and remain readable.
The readable images are illustrative native-window captures, not proof of
live provider synchronization or running-editor navigation. No new native
capture or published-package replacement was performed by this documentation
correction.

`help-discussions.png` is a native wx client-area capture of this pane,
with illustrative reviewers and comments. Its visible status says
**DEMO — no provider connected**. The views demonstrate message cards, author highlighting,
design-item chips and an inline reply composer in both tabs. They do not represent
live provider data or a running editor. No private project names, paths or
credentials were present; no redaction was needed. Source and packaged copies
are checked for equality during candidate validation; equality does not verify
image content. The intended composer capture used a synthetic attachment
thumbnail, but its black PNG is not usable evidence of that preview.
`help-setup.png` is a native setup dialog with a generic
`C:/Projects/Example` path and fictitious revision, with no sign-in performed.

## Reproduction

```console
python -m pytest review_comments_plugin/tests -q
python -m pytest tests/test_ipc_plugins.py tests/test_suite_ux.py tests/test_tool_cli.py -q
python tools/validate_docs.py --source-only
python -m review_comments_plugin.cli --help
```

Run native tests with a Python runtime supplying wx. Tests skip native GUI cases
when wx is unavailable; a skip is not a native pass. Live provider testing is a
separate explicit action against a labelled disposable conversation, with
credentials retained by the provider CLI and no user design modifications.
