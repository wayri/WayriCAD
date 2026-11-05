# WayriCAD 4.5.0

Review remains a **testing** package. This release adds a compact composer and
review context for saved BOMs and Gerbers, variant tags and orphan diagnostics.
See the [Review guide](../review_comments_plugin/README.md) for setup and limits.

## Review changes

- The compact composer keeps common formatting available. It has no separate
  Paste or Image buttons; use **More → Attach image…**, paste, or drop an image.
  Quote reply appends the selected message as a Markdown quote without sending.
- Reply headers show sender → immediate recipient, and all replies have one
  indentation level. Missing or ambiguous parents are identified as unavailable.
- A read-only saved-design BOM supports row and cell context. Existing or
  generated project-local Gerbers can be viewed and annotated when the separately
  supplied viewer supports manufacturing. Anchors retain saved-file identity.
- Variant tags retain explicit context and filter markers; they do not compute
  effective inherited variant values or infer population state.
- Orphan and changed-context diagnostics preserve the original anchor. Optional
  append-only provider status notes require stable observations and preflight;
  failed reads are not treated as deletions.

KiView is supplied separately under its own license; WayriCAD does not bundle or
relicense it. The saved viewer does not reflect unsaved editor geometry.

## Validation and limits

Source and automated checks cover the changes. A KiCad 11 development build
launched the candidate from its toolbar. The user reported KiCad 11 sign-in,
but it was not observed in the current process, which had exited. A separate
KiCad 10 native CLI run crashed with Windows status `0xC0000005`.

On Windows KiCad 10, GitHub sign-in, visible addition and deletion of comments,
and draft retention were verified. The live GitLab and browser synchronization
matrix and complete native acceptance remain incomplete. Screenshots are
illustrative source captures, not evidence of a connected provider workflow.
See [Review validation](../review_comments_plugin/VALIDATION.md) for the
recorded scope. KiCad 11 support remains experimental; Review is not claimed
fully accepted across editors or providers.
