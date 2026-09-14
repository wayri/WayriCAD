# WayriCAD BOM Studio 3.0.0

Local BOM editing and exports for KiCad 10. The desktop window runs the bundled interface through wxPython WebView and a session-authenticated loopback server. UI assets are local; no CDN, account or cloud service is needed. Dependency installation may require internet access once.

## Install

In KiCad Manager, open Plugin and Content Manager → Install from File and select the **WayriCAD BOM Studio 3.0.0 PCM ZIP**. Keep the ZIP intact. Restart KiCad and launch BOM Studio from the plugin toolbar. IPC support must be enabled in KiCad preferences. KiCad installs the package's declared `kicad-python` and `wxPython` dependencies in its plugin environment.

The UI is a separate local desktop window. Windows requires a working WebView2 runtime; Linux requires wxGTK WebKit support. If an embedded runtime is unavailable, the launcher opens the same authenticated local interface in your installed browser. Use the page’s Quit button to stop the local service. KiCad 11 compatibility is based on capability checks and an open-ended minimum version; live KiCad 11 acceptance has not been run.

## Everyday workflow

1. Open your `.kicad_pro` or root `.kicad_sch`, or explore the built-in sample.
2. Use **BOM settings** to arrange fields, labels, visibility, grouping, sorting, DNP filtering and CSV delimiters.
3. Work in the five main views: **BOM workspace**, **Variants**, **Exports & templates**, **Review & native sync**, and **Compatibility & help**. Catalogue, sourcing, checks and automation remain under **More tools**.
4. Save workspace changes to the adjacent `.wayricad-bom.json` sidecar. Undo restores settings as well as component edits.
5. Export using the saved KiCad native engine, or select a custom workspace template for staged edits. Native export reads saved KiCad source files; it does not automatically apply staged component edits. Review & native sync handles explicit backed-up source changes.

## CLI

Run from this package directory with Python 3.10 or later:

```console
python cli.py gui --demo
python cli.py gui project.kicad_pro
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
