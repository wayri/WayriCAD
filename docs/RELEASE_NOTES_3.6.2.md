# WayriCAD 3.6.2 release notes

All 17 independent KiCad 10 packages include a shared startup loading window. It stays visible while the private Python runtime is prepared and closes when the plugin window appears. Quick PI, QuickTherm and BOM Studio also show startup feedback from their desktop entrypoints.

Plugin launchers now keep KiCad and plugin command-line arguments out of wx's own option parser while wx initializes. This addresses the spurious KiCad “Unknown option 'I'” dialog seen when opening tools. The original arguments remain available to the launchers.

KiCad's External Plugins menu is a flat list and may not show every installed tool on a short display. **WayriCAD — All tools…** opens a searchable list of every registered WayriCAD action, including Quick PI. The package manager and toolbar actions remain independent.

The changes affect startup and discovery only; numerical analysis and board-write behavior are unchanged. KiCad 10.0.6 on Windows is the local native validation target. Source and package checks alone do not prove the behavior of a running editor on every platform.
