# Detailed host checklist (still pending)

Use alongside the 0.3.0 evidence runner in ACCEPTANCE.md. Earlier checks that
expected curves to be rejected are superseded: curves now need native exact
serialization/geometry checks, not blanket rejection. The checks below are an
archival detailed baseline and none are implicitly marked passed.

# Native acceptance checklist — NOT YET EXECUTED

Record KiCad exact version, Python/wx version, OS, display resolution/scaling,
plugin ZIP SHA256, project-copy hash, and screenshots/logs for every failure.
Perform these checks on an independent project, not the production original.

## Launch / UI

- [ ] Install 0.2 PCM ZIP; only one registered Constraint Studio plugin remains.
- [ ] Launch from PCB Editor; no traceback, external browser, server or prompt for credentials.
- [ ] Test 100%, 125%, 150%, 200% scaling; 1366×768 and larger displays. Verify
      all dialogs, scrolling, focus worksheet, movable tabs and splitter positions.
- [ ] Open realistic boards, including null netclass assignments; scopes/nets load.
- [ ] Select component/netclass/area; verify declared-scope filter is distinguished
      from effective inheritance; clear filters and test empty/no-match states.
- [ ] Edit every constraint form; test save/reload, unknown native preservation,
      typed errors, enable/disable, priority, undo/redo, clipboard and CSV.
- [ ] Capture multiple rules as a set; parameterize dimension, ps, layer and scope
      literal fields; bind, preview, stage, export/reload, migrate, ungroup.
- [ ] Confirm manual edits or disable of generated rules block matrix/profile replacement.

## Native rules / geometry

- [ ] Compare generated rules with KiCad syntax checking and native DRC for all
      catalogued constraints, including explicit time-based length/skew bounds.
- [ ] Create a footprint-owned area from front and back linear courtyards; open
      the review board and check the area's parent, polygon and actual layers.
- [ ] Check entirely inside A/B, inside/outside pair, boundary-touching and
      boundary-crossing traces. Verify both-enclosed clearance semantics and floors.
- [ ] Move/rotate/flip using real KiCad commands; save/reopen. Verify area geometry
      transforms correctly and no frozen F.Cu rule clause remains after a flip.
- [ ] Repeat with non-square/non-symmetric courtyard to expose coordinate/sign errors.
- [ ] Edit courtyard geometry; old area must be flagged until explicitly rebuilt.
- [ ] Duplicate and replace footprints; missing/ambiguous owner/area identities
      must be detected. Verify library update behavior rather than assuming it.
- [ ] Reject curves/multiple loops from the copying wizard; existing native areas
      remain usable. Do not substitute bounding boxes for unsupported courtyards.
- [ ] Compare inspector outcomes with native tools. Unknowns, same-net checks,
      overrides, composite classes, geometry and from-to connectivity must never
      be reported as a proven native winner by the offline inspector.

## Native integration / persistence

- [ ] Select A/B in KiCad and import selection; cross-probe matches and actual
      native report items. Confirm visible highlight and valid selection state.
- [ ] Edit/switch the active board; selection bridge must reject stale context.
- [ ] Invoke native CLI on export; refill requested, no source or export board save,
      report provenance correct, JSON loaded and actual exit codes/errors visible.
- [ ] Record local review, then change rules/board/settings; review becomes stale.
- [ ] Export does not change source. Apply while source is open is refused using
      available locks/attestation; external source edits or edited export are refused.
- [ ] With all editors closed, apply a valid review, inspect backup/journal and
      reopen in KiCad. Simulate write failure and verify rollback where feasible.
- [ ] Reopen an old 0.1 project; preserve unknown sidecar keys, native comments,
      unknown clauses, detached snapshot guards and non-plugin project settings.

Promotion to a production release requires recorded evidence; this file is a
test plan, not a set of completed checks.


## Added 0.3.1 Help acceptance — NOT EXECUTED

- [ ] Open Help with no network: all 101 topics load, search/category filtering,
      Back/Forward/Home and Copy topic work; no browser/server opens.
- [ ] Press F1 in every main and nested tab. Verify context changes correctly,
      including solver, signed review, path budgets and DRC evidence.
- [ ] Press F1 and Help from each constraint, condition/clause, BGA and profile
      capture dialog; close Help and ensure staged form values remain unchanged.
- [ ] Load all 34 form references and all 27 function references. Check all native
      glyphs, long identifiers, tables and sample native syntax are legible.
- [ ] View all eight local UI renders, fit-width/100%/150% zoom and scroll. Labels
      must remain visible; no image is described as a native screenshot.
- [ ] Check 100%, 125%, 150%, 200% Windows scaling and narrow display widths.
- [ ] External source links prompt before browser launch. Missing/corrupt help
      assets show a useful error without corrupting project state.
