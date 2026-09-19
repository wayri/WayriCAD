# Native runtime setup

WayriCAD uses KiCad 10's Python bindings and creates private dependency environments
in the user's cache directory. It never installs Python packages into KiCad itself.
Set `WAYRICAD_KICAD_PYTHON` to an alternate KiCad 10 Python executable when automatic
discovery cannot find a complete installation.

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
