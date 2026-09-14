# WayriCAD Embed3D 3.0.0

A local desktop workspace for inspecting and packaging symbols, footprints and 3D models. It incorporates the supplied 0.4.1 implementation and the 0.4.0 regression fixtures.

Install `WayriCAD-embed-3d-3.0.0-PCM.zip` directly with KiCad's Plugin and Content Manager. Enable the KiCad API under Preferences → Plugins. The new launcher uses IPC; its Python environment and dependencies are managed by KiCad.

Open a saved project, scan its component table, select the asset types to include, review the proposed operation, then write a new project folder. Original sources are preserved and generated assets are hashed. Library identifiers use `WayriCAD_Embed3D_` without display-name spaces.

IPC mode supports saved-file and existing-archive workflows. Native footprint-library normalization is not available through the current IPC API, so that option is disabled with an explanation. KiCad 10's native bridge remains available in a direct legacy source install. KiCad 11 runtime acceptance is still required; see the repository compatibility document.

The UI and icons are packaged locally. `python -m embed_3d_plugin --help` lists CLI operations. Most operations default to a dry run and require `--apply` to write. CLI embedding validates inputs, preserves model transforms, refuses unsafe paths and offers backups/recovery.

From the repository root, run `python -m unittest discover -s embed_3d_plugin/tests` for regression tests. Native tests are opt-in and are not covered by a passing pure-Python test count. Original license notices remain in LICENSE. Older documents under docs describe the imported releases and are historical.
