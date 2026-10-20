# WayriCAD 3.6.20

Resizable workspaces and complete offline help across the 23-plugin suite.

- Drag dividers to give settings, board previews and result tables the space they need. Expanded options scroll inside the workspace.
- Read complete native table rows in a searchable, resizable reader with **Ctrl+Shift+Enter**; copy selected rows with **Ctrl+C**.
- Improve Analytics Studio and Constraint Studio panel scrolling, responsive layouts and table sizing.
- Add visible Help actions where missing and improve all 23 bundled offline guides. Analytics Studio serves its help locally.
- Avoid queued dropdown callbacks accessing already-destroyed native controls.
- Include independently installable Component Arranger and Layer Counter packages, and updated Trace Refiner and Silkscreen Label Placer interfaces.

The 17 IPC packages advance to 3.6.20. Native packages are Fusion 0.9.9, Variant Manager 0.6.2, Silkscreen Labels 0.2.3, Trace Refiner 0.2.1, Component Arranger 0.1.1 and Layer Counter 0.1.1.

See [using adjustable panels and tables](UI_ACCESSIBILITY.md), the [plugin help index](HELP_INDEX.md) and the [validation record](audits/RELEASE_3.6.20.md).

## Install

Refresh the WayriCAD repository in KiCad Plugin and Content Manager, or download a PCM ZIP from the release and choose **Install from File**, without unpacking it. Restart PCB Editor after updating.

Numerical models and board-write review gates retain their existing scope. Windows native checks do not establish native GUI compatibility on every OS or display scale.
