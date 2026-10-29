# Review companion validation — 29 October 2026

This is a 0.1.0 development candidate. It has not been published or added to
the public PCM feed. The existing 3.6.42 release assets and tags are unchanged.

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

`help-workflow.png`, `help-discussions.png` and `help-composer.png` are 1120 × 960 native wx client-area captures of this pane,
with illustrative reviewers and comments. Its visible status says
**DEMO — no provider connected**. The views demonstrate message cards, author highlighting,
design-item chips and an inline reply composer in both tabs. They do not represent
live provider data or a running editor. No private project names, paths or
credentials were present; no redaction was needed. Source and packaged copies
are checked for equality during candidate validation. The composer preview uses
a synthetic thumbnail to illustrate a pending attachment; it represents no
upload. `help-setup.png` is a 760 × 660 native setup dialog with a generic
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
