# Mechanical Check OpenGL dependency startup

The menu compatibility action imported the viewer inside the editor's Python.
The standalone wrapper also bypassed dependency preparation whenever pcbnew was
already importable. That does not establish that PyOpenGL is installed, so either
path could fail with `No module named OpenGL`. IPC preparation checked the root
package instead of the GL and GLU modules that the viewer actually imports.

All GUI entry paths now prepare a private runtime before importing the viewer.
The shared mechanical profile probes both OpenGL.GL and OpenGL.GLU and requests
PyOpenGL when needed. The native action launches the viewer in a separate
prepared process; its loading window pumps editor events while dependency setup
runs in a background worker. The isolated child enters the viewer directly,
without recursively relaunching. Headless analysis and rules export keep their
existing dependency scope. KiCad's Python installation is not modified.

## Validation

Windows, installed KiCad 10.0.6 / Python 3.11.5 / wxPython 4.2.2:

- Final complete Mechanical Check suite: 112 passed, zero skipped, normal exit.
  This includes available native KiCad/FreeCAD fixture pipelines, kernel/contact
  measurements and the native workspace. Fixtures remain unchanged.
- Twelve launch/integration tests passed from source and from an unpublished
  extracted PCM package. All 91 packaged Python files compiled; the isolated
  check imported the actual viewer and actual GL/GLU modules.
- Thirteen shared runtime tests passed. Missing-dependency provisioning was
  tested with a controlled subprocess runner: pip targets the private runtime,
  requests binary wheels and leaves the native installation untouched. No new
  global package installation was performed for validation.
- Setup failures are surfaced before UI import, environment overrides are
  respected, native setup processes loading events, and the prepared isolated
  child does not enter a relaunch loop. The action captures its originating board
  before setup pumps events, so switching documents cannot redirect the viewer. README and both help copies are updated.

Actual user-toolbar activation on an installed updated package was not performed.
Successful imports do not establish OpenGL driver/context compatibility on every
machine. Existing published 3.6.32 assets and the public feed remain unchanged;
these source changes require a new validated installer release to distribute.
