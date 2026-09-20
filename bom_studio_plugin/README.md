# WayriCAD BOM Studio

<img src="icon.png" width="32" height="32" alt="WayriCAD BOM Studio icon">

Local BOM editing and exports for KiCad 10. The desktop window runs the bundled interface through wxPython WebView and a session-authenticated loopback server. UI assets are local; no CDN, account or cloud service is needed. Dependency installation may require internet access once.

## Install

In KiCad Manager, open Plugin and Content Manager â†’ Install from File and select the **WayriCAD BOM Studio 3.1.1 PCM ZIP**. Keep the ZIP intact. Restart KiCad and launch BOM Studio from the plugin toolbar. IPC support must be enabled in KiCad preferences. The toolbar launcher selects a compatible installed KiCad Python runtime and provisions its lightweight dependencies in a private WayriCAD cache. It does not build wxPython inside KiCad's managed plugin environment. Windows needs WebView2; Linux needs the distribution's wxGTK/WebKit runtime. If the native browser cannot initialize, the same fully local interface opens in your installed browser with the reason displayed.

The UI is a separate local desktop window. Windows requires a working WebView2 runtime; Linux requires wxGTK WebKit support. If an embedded runtime is unavailable, the launcher opens the same authenticated local interface in your installed browser. Use the pageâ€™s Quit button to stop the local service. KiCad 11 compatibility is based on capability checks and an open-ended minimum version; live KiCad 11 acceptance has not been run.

## Current desktop workspace

![Current WayriCAD BOM Studio desktop](help-workflow.png)

The built-in sample contains 11 components and fictional part/pricing data. The screenshot shows the three primary views; it is not an electrically validated circuit.

## Everyday workflow

1. Launch from PCB Editor to use its saved project automatically. Standalone mode can open a `.kicad_pro` or root `.kicad_sch`, or explore the built-in sample.
2. Use **BOM settings** to arrange fields, labels, visibility, grouping, sorting, DNP filtering and CSV delimiters.
3. Work in three main views: **BOM workspace**, **Exports & templates**, and **Review & native sync**. Variants, help, catalogue, sourcing, checks and automation remain under **More tools**.
4. Save workspace changes to the adjacent `.wayricad-bom.json` sidecar. Undo restores settings as well as component edits.
5. Export using the saved KiCad native engine, or select a custom workspace template for staged edits. Native export reads saved KiCad source files; it does not automatically apply staged component edits. Review & native sync handles explicit backed-up source changes.

## Simple exports

![Native simplified export preview](help-simple-exports.png)

Choose **Exports & templates**, a saved template, then **Bill of materials**, **Test points only**, or **DNP only**. The default BOM excludes test points and DNP components. Toggle either condition as required. **Group matching components** produces quantities and reference groups; turn it off for one component per row. Existing safety grouping separates differing packages and procurement data.

**Preview rows** shows the staged workspace data that the export uses. Choose CSV, XLSX, HTML or another supported format and Export. Errors still block release exports unless you explicitly mark the output as draft. Separate test-point and DNP lists include parts excluded from the normal BOM.

Test-point detection uses TP-number references (for example TP12) or the component field `TestPoint=yes`; `TestPoint=no` explicitly opts out. Use bulk field editing to classify nonstandard reference names. DNP lists use the native DNP flag. These are schematic component lists, not PCB test-pad coordinate reports.

Expand **Templates, native exports and advanced settings** to edit, duplicate, import or share full templates, and to use saved-source KiCad exports. Quick export conditions are session choices; saved templates and project files are unchanged by preview or export. Editing and bulk editing remain in BOM workspace. Native source changes still require reviewed sync.

## CLI

Older hierarchical projects can be upgraded through **Review & native sync > Upgrade project copy**. Select a new directory outside the source project. KiCad 10 upgrades every sheet; WayriCAD restores legacy annotation and power-net semantics, then compares native connectivity and component fields before publishing the copy. The original project stays unchanged. Unsupported or ambiguous hierarchies are rejected with a reason. Consistent multi-unit components spanning several sheets are grouped and edited together.

Run from this package directory with Python 3.10 or later:

```console
python cli.py gui --demo
python cli.py gui project.kicad_pro
python cli.py upgrade-copy legacy/project.kicad_pro --destination modern-project
python cli.py bom-format show project.kicad_pro
python cli.py bom-format configure project.kicad_pro --config settings.json
python cli.py export project.kicad_pro --format csv --acknowledge-saved-only --output bom.csv
python cli.py --help
```

`settings.json` contains `bom_settings` (including `fields_ordered`) and `bom_fmt_settings`. The **bom-format show** response exposes the current `preset` and `format` objects to use as these values. Configure updates the sidecar and preserves native files. `gui --ui none` starts the local headless service; `--ui browser` selects the local browser directly. CLI output refuses accidental overwrites.

Advanced tools include assembler and distributor exports, reusable custom templates, field inventories, variants, local parts catalogues, asset previews, checks and job sets. Supplier integrations are opt-in. STEP/IGES/BREP preview requires the optional packages listed in `requirements-preview.txt`; BOM editing and VRML/STL previews do not.

## Validation and licensing

Run `python -m unittest discover -s tests` from this directory. Contract tests do not establish native-editor equivalence or manufacturing qualification. Read the suite release validation report for actual host checks.

The imported BOM Studio implementation retains its original MIT license and copyright in [LICENSE](LICENSE). Suite bundles also include shared GPL-licensed runtime code with its own notice. The PCM package declares the combined distribution license. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for bundled asset attribution. Version-specific documents under `docs/` describe historical feature development; this README is the current installation guide.
