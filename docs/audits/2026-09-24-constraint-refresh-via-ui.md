# Constraint Studio saved-board refresh and via-profile check

Windows, KiCad 10.0.6, Python 3.11.5 prepared KiCad-compatible runtime, wxPython 4.2.2 / wxWidgets 3.3.2. Source branch `codex/wayricad-discoverability`; this is a 3.4.0 candidate, not a published release.

The KiCad 10 two-atom net form `(net "CAN_P")` was absent from Studio's layout inspection. The parser now recognizes it. Studio compares the saved board with the loaded snapshot, reloads a clean workspace on focus, and provides an explicit reload action. Dirty staged edits prevent reloading until exported or undone. Routing drafts are reset when the board revision changes so the net picker and previews use the new snapshot.

The routing page now has shared-scale, parallel trace/pair previews beside each layer's physical stackup; editing width or pair gap changes the copper geometry immediately. Via type, copper diameter, drill and non-through layer span are reviewable profile inputs. Native rules enforce their dimensions and permitted type/span; the UI can copy saved netclass via sizes. KiCad does not automatically switch via type from a tuning profile, so the router's explicit via-type selection is still required.

Evidence:

- `python -m pytest protocol_constraint_composer_plugin/tests tests/test_layer_routing.py -q`: 352 passed, 11 skipped, 16 subtests passed.
- `python -m pytest tests -q`: 322 passed, 67 skipped, 141 subtests passed.
- Prepared runtime `tools/smoke_layer_routing.py --net-groups`: native WebView loaded and completed the preview, via preview and stage, width estimator, net picker, protocol tabs, native bridge stage and undo checks with no JavaScript errors. Output: ignored `.validation/routing-ui-via-native.json`.
- KiCad 10.0.6 CLI DRC parsed a generated microvia rule and reported a deliberately incorrect through via's type/span and dimensions. Output: ignored `.validation/via-rule-native/drc.json`. This is a negative test fixture, not a clean production board.
- `python build_pcm.py --output-dir .validation/current-routing-candidate`: 16 disposable PCM ZIPs; `python tools/validate_packages.py --archive-dir .validation/current-routing-candidate` and `python tools/validate_docs.py` passed.

The native WebView startup aborted with `COREWEBVIEW2_WEB_ERROR_STATUS_CONNECTION_ABORTED` under the filesystem sandbox in both KiCad's base Python and the prepared runtime. The identical prepared-runtime smoke passed outside the sandbox. No owned user PCB was written. A live differential-pair layer-transition mouse test was not part of these automated checks; passing rules, staging and preview tests do not establish that router behavior.

Follow-up acceptance: the user confirmed that differential-pair routing across
layers works in their KiCad session. This is user-reported acceptance, without a
captured board or measured trace/gap values in this audit. A separate disposable
source fixture passed stage → export → `apply_bundle(project_closed=True)` →
reopen: the reopened project contained the native two-layer profile (0.20/0.30
mm), through-via recipe and generated via rules, with a backup directory
created. No owned user board was modified. The new **Open Apply Review** action
launches the exported helper; a mocked launch check confirmed its path and
stale-export guard. The helper retains its own project-closed acknowledgement
and confirmation before writing.
