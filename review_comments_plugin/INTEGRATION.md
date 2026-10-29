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
| GitHub | `/repos/OWNER/REPO/issues/N` and `/comments`, 100/page | POST the same comment collection | `gh auth login --web`; token read only in backend via `gh auth token` |
| GitLab | `/projects/ENCODED_PATH/issues/N` or `/merge_requests/N`, plus `/notes` | POST the same note collection | `glab auth login --web`; `glab api` resolves keyring/OAuth credentials itself |
| GitHub Discussions | GraphQL `repository.discussion`, complete comments/replies cursor pages | `addDiscussionComment` with actual `discussionId` and optional `replyToId` | Same backend-only gh credential boundary |

GitHub general comments are not inline PR review comments. Discussions use a
separate provider adapter, tab, conversation number and cache identity. Opaque
GraphQL node IDs are preserved; native reply relationships override annotation
metadata. Replying to a reply targets its top-level native Discussion thread.
GitLab issue-board names use `/projects/ENCODED_PATH/boards`. GitHub Projects
opens its browser UI; no invented REST replacement for Projects GraphQL exists.
Tokens never enter the pane, marker, cache or settings. GitHub transport rejects
redirects, including same-origin redirects. GitLab transport uses configured
`glab api`; its installed CLI owns HTTP and credential transport behaviour.

## UI synchronization and capabilities

`ReviewSession.refresh()` returns current provider rows with `id`, `root`,
`body`, `author`, `updatedAt`, `url`, and validated `anchors`. Failures keep old
data explicitly stale. The pane serializes network tasks, polls every eight
seconds while active, backs off to 120 seconds and rejects closed/hidden UI
updates. Participants are authors, never claimed as online presence.

Native PCB selection uses `wayricad_runtime.analysis_selection` with explicit
source hash and launching-editor context. No schematic API or transient region
overlay is assumed. Unsupported navigation reports its limitation and keeps
provider coordinates intact. This version publishes manually entered regions;
it does not provide drag-to-select region capture in the PCB viewport.

## Packaging and adoption

The plugin directory is self-contained except for `wayricad_runtime`, which
the existing PCM builder vendors into each IPC ZIP. `plugin.json` exposes a PCB
action; `wayricad-tool.json` loads `action.ReviewPlugin`. Importing the source package
does not register actions. `python -m review_comments_plugin.cli` supplies CLI
access. No KiView files are edited by this companion.

This development candidate has its own 0.1.0 testing metadata. Before public
suite adoption: align the version with the next suite release and finish the
remaining authenticated-provider and running-editor checks. Catalogue/help,
inventory, suite CLI, wheel package-data and CI test registration are prepared.
Do not promote a candidate feed as if unavailable host checks had passed.

Confirmed GitLab uploads carry the shared attachment fields `provider`, `host`,
`repository`, `projectId`, `mime`, `url`, `width` and `height`. PNGs are normalized
to at most 1024 pixels per side before preview/upload. Upload receipts and URLs
are validated against the chosen provider/project before they enter a marker.
Removing an image link from the composer also removes its pending metadata.
