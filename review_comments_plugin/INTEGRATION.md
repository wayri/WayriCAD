# Pocket KiView / WayriCAD Review integration contract

## Ownership and source identity

GitHub or GitLab is authoritative. This companion fetches the selected general
conversation's root and complete comment pages. Cache identities include
provider, HTTPS host, repository, immutable commit, design path, conversation
kind and number. A complete refresh replaces that conversation's cached rows;
deleted provider comments therefore disappear. An incomplete read never claims
completeness. Pending drafts are stored separately with `status: unpublished`.

Public anchors contain no local absolute path, username, API credential or IPC
socket. The local worktree/file must byte-match `git show COMMIT:PATH` when the
session opens, allowing only LF/CRLF text-checkout conversion. No Git clean or
smudge filter is executed. The exact local bytes' SHA-256 is checked again before/after reads/navigation and
before publication. The plugin never writes PCB/schematic content. Saved-byte
checks cannot certify unsaved editor state; selection links object identity.

## Shared marker

The wire format matches KiView `extension/review-comments.js`:

```text
<!-- kicad-review:v1 BASE64URL_UTF8_JSON_WITHOUT_PADDING -->
```

The JSON has `id`, `text`, `createdAt`, `updatedAt`, `severity`, `state`, `tags`,
`mentions`, `remoteRefs`, and `anchor`. New notes use UUID identifiers, UTC
timestamps, `info` severity and `open` state. `replyTo` is an optional extension;
the human-readable reply also links the provider comment.

`anchor` requires `repository`, full commit `ref`, and repository-relative
`file`. GitHub is the default provider. GitLab also requires
`provider: gitlab` and HTTPS origin `host`. Optional `uuid`, `objectId`,
`reference`, `netName`, `kind`, `variant`, `position: {x,y}` and
`area: {x,y,width,height}` match KiView. Coordinates are mm, board-top XY.
The companion deliberately accepts immutable commit IDs only, so legacy
branch-named KiView anchors remain visible text but are not natively located.

The companion derives publication identity from the provider response, never
from marker `remoteRefs` or a local file. New posted markers have empty
`remoteRefs`; the provider readback supplies the actual thread/comment receipt.
Malformed, foreign-host and foreign-file markers are not navigable. Text is
displayed with native text widgets, without executing HTML or Markdown.

## Provider routes and authentication

| Provider | Read | Publish | Auth |
| --- | --- | --- | --- |
| GitHub | `/repos/OWNER/REPO/issues/N` and `/comments`, 100/page | POST the same comment collection | Current-source desktop OAuth device flow; default `public_repo write:discussion`, optional private `repo write:discussion` |
| GitLab | `/projects/ENCODED_PATH/issues/N` or `/merge_requests/N`, plus `/notes` | POST the same note collection | Current-source desktop OAuth device flow with `api` scope; device grant must be enabled |
| GitHub Discussions | GraphQL `repository.discussion`, complete comments/replies cursor pages | `addDiscussionComment` with actual `discussionId` and optional `replyToId` | Same current-source desktop authority as GitHub comments |

GitHub general comments are not inline PR review comments. Discussions use a
separate provider adapter, tab, conversation number and cache identity. Opaque
GraphQL node IDs are preserved; native reply relationships override annotation
metadata. Replying to a reply targets its top-level native Discussion thread.
GitLab issue-board names use `/projects/ENCODED_PATH/boards`. GitHub Projects
opens its browser UI; no invented REST replacement for Projects GraphQL exists.
Current-source desktop tokens remain in process memory only. The authority
expires them after eight hours or the provider's shorter lifetime, measured
against wall and monotonic clocks; activity never extends the deadline. There
is no automatic refresh, CLI fallback or token paste. Closing the process
loses sign-in. Expiry and Review sign-out block reads, publication, uploads and
native navigation, clear canvas marker authority and preserve local drafts.
Sign-out does not change browser, KiView extension or shared CLI sessions.
Self-hosted GitLab requires a public device-flow client ID supplied as
`WAYRICAD_REVIEW_GITLAB_CLIENT_ID`; a disabled device grant fails explicitly.
Tokens never enter the pane, marker, cache or settings. The desktop transport
rejects redirects; CLI commands retain separate legacy `gh`/`glab` auth.

## UI synchronization and capabilities

`ReviewSession.refresh()` returns current provider rows with `id`, `root`,
`body`, `author`, `updatedAt`, `url`, and validated `anchors`. Failures keep old
data explicitly stale. The pane serializes network tasks, polls every eight
seconds while visible (including an inactive window beside KiCad), backs off
to 120 seconds and pauses hidden/minimized/closed or signed-out polling.
Participants are authors, never claimed as online presence. Provider snapshots
replace additions, edits and deletions; stale reads remove marker authority
while retaining unpublished drafts. No background operation publishes a draft.

Native PCB selection uses `wayricad_runtime.analysis_selection` with explicit
source hash and launching-editor context. Native schematic selection and native
KiCad canvas overlays are not assumed. Unsupported navigation reports its
limitation and keeps provider coordinates intact.

## Embedded saved-design review canvas (4.4.0)

The current source embeds KiView in a wx WebView. It reads saved PCB and
schematic source, offers a selector for the paired file and schematic hierarchy
files, and supports independent pan, zoom, PCB layer visibility, PCB 3D and a
separate comment overlay. Pins and regions can be drafted in 2D; the 3D view
has no verified inverse screen-to-mm mapping for drafting. The current document
catalog does not supply component model assets, so 3D uses stand-ins where
models would be needed. STEP models are outside this integration. Design edits
remain in KiCad.

`ReviewDocuments` catalogs exact saved files and limits source reads. The
selected file's SHA-256 is checked before and after loading and before canvas
events. `ReviewSession` still owns provider, immutable commit and file scope.
The canvas receives provider-read markers only when its path and SHA match the
synced session. Drafted anchors remain local until an explicit provider send;
the viewer's displayed geometry never authorizes publication. An unsaved KiCad
change is outside this saved-file scope.

The WebView host serves an allowlisted in-memory asset snapshot over an
ephemeral `127.0.0.1` port with a random path. It closes with the pane. The
source tree is supplied through `WAYRICAD_REVIEW_VIEWER_ROOT` or **Viewer
assets…**; Review leaves KiView externally supplied under its separate distribution
license; it does not bundle or relicense those assets. There is no fixed port, remote asset fetch or provider
credential bridge in this host. The Windows source window has passed visual
checks with a saved KiCad 10 fixture; this does not establish native editor
attachment or live provider authentication. See [validation scope](VALIDATION.md).

### Native editor boundary

The embedded canvas navigates its own saved-file rendering. It does not inherit
live KiCad viewport, sheet, selection, layer state or unsaved changes. PCB
object-linked comments can request selection in the originating editor through
the existing IPC path; schematic selection remains unsupported. The overlay is
outside PCB/schematic files, ERC/DRC markers, fabrication output and undo.
Native editor attachment and provider-backed end-to-end acceptance remain
pending.

The current-source native header keeps one Light/Dark toggle and Account action.
**More** contains settings, refresh, reviewer highlights, workflow, design
visibility and Review sign-out. Filters and the PCB layer list start collapsed;
the theme applies to native controls and the embedded viewer. The final Windows
source window and light/dark themes have passed visual checks with local
illustrative comments. Live OAuth has not been accepted.

Sources: [add-on capabilities](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/),
[IPC transport](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-kicad-developers/),
[shared editor methods](https://docs.kicad.org/kicad-python/project.html),
[PCB methods](https://docs.kicad.org/kicad-python/board.html),
[schematic methods](https://docs.kicad.org/kicad-python/schematic.html).

## Packaging and adoption

The plugin directory is self-contained except for `wayricad_runtime`, which
the existing PCM builder vendors into each IPC ZIP. `plugin.json` exposes a PCB
action; `wayricad-tool.json` loads `action.ReviewPlugin`. Importing the source package
does not register actions. `python -m review_comments_plugin.cli` supplies CLI
access. No KiView files are edited by this companion.

Published Review 4.3.0 is a testing package without this embedded canvas or
direct desktop OAuth sign-in. Its CLI-based auth remains historical behavior.
Source-window visual checks do not establish installed-package, running-editor
attachment or live-provider acceptance. Keep those checks explicit;
a candidate feed does not establish that unavailable host checks have passed.

Confirmed GitLab uploads carry the shared attachment fields `provider`, `host`,
`repository`, `projectId`, `mime`, `url`, `width` and `height`. PNGs are normalized
to at most 1024 pixels per side before preview/upload. Upload receipts and URLs
are validated against the chosen provider/project before they enter a marker.
Removing an image link from the composer also removes its pending metadata.
