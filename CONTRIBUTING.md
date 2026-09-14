# Contributing to WayriCAD

WayriCAD is a collection of independent KiCad IPC plugin packages sharing a
PCM feed. Changes must preserve package isolation: a plugin ZIP cannot import
code from a sibling package after PCM installation.

## Development workflow

1. Create a branch from `develop`.
2. Keep behavioral changes scoped to the affected plugin. Shared IPC and routing
   code belongs in `wayricad_runtime`; the builder vendors it into each ZIP.
3. Use KiCad's bundled Python for pcbnew/wx runtime checks:

   ```powershell
   & 'C:\Program Files\KiCad\10.0\bin\python.exe' -m compileall -q <plugin-directory>
   ```

4. Run the repository tests with `python -m unittest discover -s tests -v`.
5. For PCB-writing tools, verify non-mutating review, stale-plan rejection,
   explicit commit, rollback on failure, and grouped undo/redo.
6. Run DRC on representative boards and test KiCad light and dark themes.
7. Update `help.html`, package `ReadMe.md`, metadata, versions, and PCM feed
   whenever user-visible behavior changes.

## Pull requests

Include the KiCad version, operating system, package name, reproduction steps,
before/after screenshots, and a minimal test board when geometry is involved.
Document pcbnew API assumptions and engineering limitations. Generated results
must not be presented as replacing ERC, DRC, field solving, SI simulation, or
physical measurement.

## Safety expectations

- Never write board geometry before an explicit commit action.
- Keep preview geometry in memory until commit.
- Preserve net names, layers, dimensions, and deterministic ordering.
- Treat selection and highlighting as cross-navigation, not proof of validity.
- Make bulk commits identifiable and recoverable after the plugin closes.
