# Contributing to KiWay

KiWay is a collection of independent KiCad ActionPlugin packages sharing a
PCM feed. Changes must preserve package isolation: a plugin ZIP cannot import
code from a sibling package after PCM installation.

## Development workflow

1. Create a branch from `develop`.
2. Keep behavioral changes scoped to the affected plugin and copy genuinely
   shared standalone helpers into every package that ships them.
3. Use KiCad's bundled Python for pcbnew/wx runtime checks:

   ```powershell
   & 'C:\Program Files\KiCad\10.0\bin\python.exe' -m compileall -q <plugin-directory>
   ```

4. Run the repository tests with `python -m unittest discover -s tests -v`.
5. For PCB-writing tools, verify all four stages: window preview, temporary PCB
   preview, commit, and grouped undo/redo after reopening the plugin.
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

- Never write board geometry before an explicit PCB-preview/commit action.
- Keep temporary geometry removable on close.
- Preserve net codes, layers, dimensions, and deterministic ordering.
- Treat selection and highlighting as cross-navigation, not proof of validity.
- Make bulk commits identifiable and recoverable after the plugin closes.
