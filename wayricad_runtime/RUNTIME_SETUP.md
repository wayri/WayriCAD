# Native runtime setup

WayriCAD uses KiCad 10's Python bindings and creates private dependency environments
in the user's cache directory. It never installs Python packages into KiCad itself.
Set `WAYRICAD_KICAD_PYTHON` to an alternate KiCad 10 Python executable when automatic
discovery cannot find a complete installation.

The shared loading window remains visible while dependencies are prepared and
the plugin starts. It hides immediately when the plugin signals readiness or
its startup process exits, before the launcher waits for the open plugin to
close. Startup errors clear the loading window before displaying their error
message. This lifecycle is shared by the independently installed IPC packages.

## Native electrical windows

The SI/RLC saved-board launcher performs its first native PCB read before
creating `wx.App`, then passes that board into the analysis frame without a
second parse. Reversing the order reproduced a native shutdown hang on Windows
KiCad 10.0.6 with Python 3.11 and wxPython 4.2.2. Source hashes bracket loading
and frame preparation; changed files cannot open as the original snapshot.

Use `native_analysis.main` for this lifecycle. Native GUI tests prepare/read
their synthetic fixture before wx startup and copy its bytes per case; they
must not infer GUI compatibility from a process that only prints test success
but never exits. Geometry-only workers do not create a wx application.

Dependency installation uses binary wheels. Corporate mirrors, proxies and offline
wheel directories can be configured through standard pip configuration or environment
variables: `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `PIP_FIND_LINKS`, `PIP_NO_INDEX`,
`PIP_PROXY`, `PIP_CERT`, `PIP_CLIENT_CERT`, `PIP_CACHE_DIR` and `PIP_TRUSTED_HOST`.
Only these access/source settings are forwarded. Installation destination overrides
such as `PIP_TARGET`, `PIP_PREFIX` and `PIP_USER` are deliberately ignored.

For offline installation, prepare wheels for the target operating system and KiCad
Python version, set `PIP_NO_INDEX=1`, and set `PIP_FIND_LINKS` to the wheel directory's
file URL (for example `file:///C:/wayricad-wheels`). Include transitive dependencies.
For a path containing spaces, use a file URL with `%20` in place of each space.
Restart KiCad after changing environment variables so plugin processes inherit them.

On Linux, install the distribution's KiCad Python bindings, wxPython and Python venv
support first. WayriCAD does not attempt to compile wxPython. A runtime setup error
includes the persistent log path; check that log for the missing wheel, connection
failure or unavailable operating-system dependency. Logs can contain package-source
addresses; review them before sharing.
