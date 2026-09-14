# WayriCAD 3.0.0

A suite of 19 local KiCad tools for PCB planning, design review, BOM management, and portable projects. This release brings the former suite and the supplied BOM Studio and Embed3D applications under one name.

**Release status: testing.** KiCad 10 is the primary validation target. Packages now use KiCad's IPC plugin format, the forward path for KiCad 11. This does not constitute certification of every operation on KiCad 11; see [compatibility and verification](docs/COMPATIBILITY.md).

## Install

1. Download the individual `WayriCAD-<tool>-3.0.0-PCM.zip` files from [Releases](https://github.com/wayri/WayriCAD/releases).
2. In KiCad Manager, open **Plugin and Content Manager → Install from File** and select a ZIP directly.
3. In Preferences → Plugins, enable the KiCad API and configure a supported Python interpreter. Restart KiCad after installation.
4. Open a PCB and launch the installed tool from its toolbar action or plugin menu.

Each ZIP includes its own runtime, local help and icons. No other WayriCAD plugin is required. KiCad creates a Python environment and installs declared dependencies on first setup; internet or a pre-populated local wheel cache is needed for that step. Application pages, scripts, previews and project processing run locally. Optional network actions remain explicit.

To use the repository feed, add `https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json` to PCM's repository list once the release is published.

For a source install, build the packages, then run `python tools/install_suite.py` to inspect the destination and `python tools/install_suite.py --apply` to install. Use `--destination` for a redirected Documents directory. Existing installations are backed up outside the plugin directory. `install.bat` wraps the same installer.

## Migration

WayriCAD uses new package IDs. Remove the old suite's PCM entries to avoid duplicate toolbar actions, then install the new packages. Keep project backups and existing BOM workspaces; the installer does not delete project data. Do not install the original supplied ZIPs alongside their integrated replacements.

Historical release notes remain available under `docs/`. Their version-specific behavior is archival; this README describes 3.0.0. Original copyright and third-party license notices are preserved.

## Tools

| Tool | Purpose |
|---|---|
| BOM Studio | Local component table, variants, catalogue, native KiCad BOM fields/grouping/format settings and exports |
| Embed3D | Embed models, inspect project assets, archive footprints and rebuild portable project copies |
| Fanout Generator | Configurable fanout patterns, placement review, obstacle rejection and grouped commits |
| Via Stitching | Square or staggered stitching with copper, outline, clearance and exclusion checks |
| Bulk Label Editor | Review references, values, fields and PCB text edits; undo and redo |
| Pin Extractor | Pins, ICDs, connectivity, diagrams and document exports |
| Harness Workbench | Connector maps, wire links, validation and system harness reports |
| Heater Designer | PCB heater geometry and thermal estimates |
| Planar Magnetics | Coils, actuators and engineering estimates |
| Localizer | Project library and asset localization |
| Manufacturing Readiness | Fabricator checks, DRC/jobset gates and hashed release archives |
| PDN Decoupling | Decoupling placement analysis |
| Portable Assets | Project asset analysis, localization and recovery |
| Protocol Constraint Composer | Review and generate project rule blocks |
| Return-Path Auditor | Return-path transitions and discontinuity review |
| Signal Integrity Advisor | Electrical and layout estimates |
| Test Point Descriptor | Test-point documentation and fixture generation |
| Trace Impedance | Trace geometry, RLC and impedance estimates |
| Variant Workbench | Review and generate design variants in project copies |

## Routing workflow

Configure dimensions and scope, select **Preview**, inspect the pan/zoom canvas and optional candidate table, then **Apply**. The preview stays in the tool until commit. Geometry changes invalidate the reviewed plan. Undo/redo retain recovery information when a board operation fails.

Fanout supports selected-footprint and detected net-class scope, a selectable output copper layer, and a dedicated via-in-pad output mode. Advanced controls include outward/inward dogbone, BGA/LGA grid, radial/quadrant/corner patterns, angle and XY offsets, track dimensions and via dimensions. Stitching controls include grid pattern, spacing, target net, layer span, edge inset, clearance and reference exclusions. Rejections are reported instead of silently omitted. Conservative obstacle checks can reject usable locations; KiCad DRC remains the final board check.

## CLI

Install the source CLI with `python -m pip install -e .`. `wayricad --help` and `wayricad capabilities` describe the document and automation interfaces. [CLI guide](docs/CLI_USER_GUIDE.md).

Routing uses KiCad 10's Python interpreter (the interpreter that can import `pcbnew`):

```text
python -m wayricad_runtime.cli fanout plan --board board.kicad_pcb --settings fanout.json --output plan.json --svg preview.svg
python -m wayricad_runtime.cli fanout apply --board board.kicad_pcb --plan plan.json --output board-fanout.kicad_pcb
python -m wayricad_runtime.cli stitching plan --board board.kicad_pcb --output stitch-plan.json --svg stitch-preview.svg
```

Apply recomputes the reviewed plan and refuses changed boards, changed geometry, or an existing output path. Run `python -m embed_3d_plugin --help` for saved-project embedding tools. From `bom_studio_plugin`, run `python -m bomstudio --help` for BOM Studio commands. The routing file CLI still uses KiCad 10 SWIG; IPC GUI packaging and headless file processing have different compatibility constraints.

## Build and verify

```text
python -m pip install -e ".[test]"
python tools/prepare_suite.py
python tools/generate_suite_icons.py
python -m unittest discover -s tests
python build_pcm.py --clean-feed --release-tag 3.0.0 --branch develop
python tools/validate_packages.py
```

Run the imported applications' suites separately: `python -m unittest discover -s embed_3d_plugin/tests` and, from `bom_studio_plugin`, `python -m unittest discover -s tests`. Native geometry tests require KiCad's Python. Optional native tests and IPC tests report skips when their runtimes are unavailable; skips are not compatibility evidence.

The builder creates independent, deterministic ZIPs, a clean PCM feed and a repository icon archive. PCM icons are 64×64; toolbar assets include 24, 48 and 96 pixel light/dark variants. Schemas are checked in from the official KiCad source mirror for local validation.
