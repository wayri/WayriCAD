# WayriCAD 4.4.0

Review adds a saved-design workspace for PCB, schematic and PCB 3D navigation,
in-view comment markers, simpler browser sign-in and a single light/dark toggle.
The [illustrated user guide](../review_comments_plugin/USER_GUIDE.html) covers
installation, provider setup, saved-revision identity, commenting and recovery.
Open it from **More → User guide** in the Review window.

## Review workspace

- Open a saved project, board or schematic and navigate the paired board and
  schematic hierarchy independently. Pan, zoom, fit and select PCB layers.
  Existing comments can focus their saved positions; a marker opens its thread.
- Draft a point or region in a matching, synchronized 2D document, inspect the
  local draft and explicitly send it to the configured provider conversation.
  Design editing remains in KiCad. Saved views do not inherit unsaved editor
  changes or the main editor's camera state.
- The compact toolbar keeps layers, comment tools and filters collapsed until
  needed. One theme button updates native controls and the embedded drawing.
  Search cues, scroll rails and pane separators use the selected palette.
  Offscreen comment cards retain their full height while scrolling.
- Provider comments refresh automatically while Review is visible beside the
  main editor. Complete snapshots update additions, edits, deletions and their
  matching design markers. Hidden/minimized and signed-out panes pause, failed
  reads back off, and drafts remain local until explicitly sent.
- Online KiView comment markers were round-tripped through its actual parser,
  Markdown and JSON serializers for GitHub/GitLab PCB/schematic points and
  regions. Review retains exact provider, commit and saved-file identity.

The renderer is supplied separately through **Design options → Viewer assets…**
or `WAYRICAD_REVIEW_VIEWER_ROOT`. Its source-available license is separate from
WayriCAD's GPL license; this release does not bundle or relicense it. Read the
renderer supplier's terms before use. The asset host checks the complete
selected module closure and refuses missing or unexpected dependencies.

## Desktop sign-in and drafts

**Sign in → Sign in browser** uses a provider device-code flow. The user
approves access in the browser. Desktop Review no longer needs token paste or
the provider CLI for this flow; the separate command-line tools retain their
existing CLI authentication.

Desktop credentials stay in process memory. Sign-in ends after at most eight
hours, sooner if the provider token expires, or on process exit or explicit
Review sign-out. Activity does not extend it. Expiry blocks provider operations
and removes comment-marker authority while retaining local drafts. GitHub
private-repository scope is opt-in. Self-hosted GitLab needs a public device-flow
client ID and device-grant support.

## Validation and limits

Native Windows checks used KiCad 10's Python 3.11.5, wxPython 4.2.2 and Edge
WebView2. Actual windows rendered the public PIC programmer board/schematic,
illustrative comment markers and a 3D board with approximate component
stand-ins. Point drafting, theme switching, splitter resizing and scrolling
were exercised. No provider write or native design edit was performed by those
visual checks. The new direct OAuth flow has mocked protocol/session tests and
native dialog tests; real provider browser approval remains unverified.

Current Review canvas acceptance does not establish a connected KiCad 11
editor workflow or native Linux/macOS GUI acceptance. PCB object cross-probing
needs the originating editor IPC connection. Native schematic selection and
native KiCad canvas overlays remain unsupported. Linked component model assets,
STEP models and inverse 3D point drafting are outside this integration.

KiCad 10 remains the supported baseline. The existing KiCad 11 development
saved-board compatibility adapter and its limits are unchanged; see
[4.3.0 evidence](RELEASE_NOTES_4.3.0.md) and
[the compatibility record](COMPATIBILITY.md). Review remains a testing package.
See [Review validation and screenshot provenance](../review_comments_plugin/VALIDATION.md).

Local release checks passed archive, private feed/documentation and isolated
wheel import/CLI validation. Packaging contracts passed 38 tests and 26 subtests
with three explicit opt-in skips. Focused native UI/synchronization checks passed 46 cases,
host-adapter checks 33 cases, and direct desktop auth/session/dialog checks
19 cases; actual online-parser interoperability passed nine cases.
Skips and mocked authorization tests are not live editor or provider
acceptance. The release's CI link identifies the final source commit and full
automated matrix.
