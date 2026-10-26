# Start WayriCAD Analytics Studio

[Download release 3.6.32](https://github.com/wayri/WayriCAD/releases/tag/v3.6.32) ·
[Full guide](README.md) · [Installation](../docs/INSTALLATION.md)

Install the PCM ZIP directly with KiCad Manager → Plugin and Content Manager → Install from File. Restart KiCad, enable its IPC API in preferences, and launch Analytics Studio from the plugin toolbar.

The interface runs locally in a wxPython desktop window, with an installed-browser fallback when the embedded runtime is unavailable. When launched from PCB Editor, its saved project opens automatically. For standalone use choose **Change project**. Review parts and missing fields, edit values or fitted/DNP status, set **BOM settings**, then **Export BOM**. **Save workspace** preserves staged edits; **Review & native sync** is the separate reviewed step that writes them to KiCad files. **Copper & routing** analyzes a saved PCB by layer, net and component without requiring a schematic or BOM. Its separate worker can be canceled. Main navigation views cover daily work; **More tools** contains optional advanced workflows.

See [README.md](README.md) for desktop dependencies, the saved-native-data distinction, CLI examples and validation limits. See [help.html](help.html) for an offline quick reference.
