# Shared loading window lifetime

Validated on Windows with KiCad 10.0.6, its Python 3.11.5 runtime and wxPython 4.2.2. Portable checks and packaging used Python 3.14.2.

## Reproduction and correction

The generic `WayriCAD — Loading` frame remained visible after its plugin opened. In native KiCad Python, calling the old `LoadingWindow.finish()` left `window.IsShown()` true immediately afterward. wx queues top-level destruction until an event-loop turn. After receiving the child's ready marker, the parent launcher calls `finish()` and then blocks in `process.wait()`, so the queued destruction cannot clear the visible frame while the plugin stays open.

`finish()` now hides the frame synchronously before queuing destruction. It remains idempotent. The loading object also takes ownership of the frame immediately after construction, so a failed panel/control setup clears the partially constructed window. Runtime preparation, originating editor context and the per-launch ready marker are unchanged.

The fix is carried by all 17 independent IPC packages. Their candidate metadata and source version constants, the suite wheel and BOM API version are aligned at 3.6.13. Fusion and Variant Manager versions are unchanged. Public PCM metadata and published assets have not been replaced.

## Acceptance evidence

- KiCad Python: 12 loading/launcher/native-analysis tests passed, including two actual wx tests. The readiness handoff checked that the loading frame was hidden before entering the blocking child wait, with a plugin stand-in still shown. A failed control construction left no visible loading frame. Portable tests also covered child exit without readiness and loader cleanup before reporting a runtime-setup error.
- Shared portable suite: 402 passed, 73 skipped, 152 subtests passed. Skips are not passes. The first collection attempt lacked `jsonschema`; using the existing build dependencies resolved it.
- Built 19 disposable PCM ZIPs. Official schemas, runtime isolation, actions, icons and Python syntax passed validation. All 17 vendored `loading.py` files matched the corrected source byte for byte.
- Fresh native process using the extracted Quick PI package's shared runtime and a real separate wx child process: readiness handoff passed, loading frame was hidden before the parent's blocking wait, child exited successfully, and the disposable PCB hash stayed unchanged. The child used a bounded wx event pump; this establishes the shared loader handoff, not a live KiCad toolbar action.
- Built the 3.6.13 source archive and wheel. Building a wheel through automatic source-archive extraction hit a Windows sandbox path-access error; a direct source wheel build succeeded. The isolated wheel CLI/report/BOM/transient/electrothermal smoke passed. Its localhost BOM fixture required running outside the sandbox because the sandbox denied loopback access; no installation or publication occurred.
- `python tools/validate_docs.py --source-only` and `git diff --check` passed.

## Remaining native limitation

An expanded Quick PI child-window experiment showed its frame and then hit Windows heap error `0xc0000374` in the full wx event loop. It did not pass and is not counted as plugin-window acceptance. The shared native tests and extracted-runtime handoff above passed independently of that experiment. No live KiCad IPC toolbar launch or update of installed plugins was performed in this change.
