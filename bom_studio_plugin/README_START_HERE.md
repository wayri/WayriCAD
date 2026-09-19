# Start WayriCAD BOM Studio 3.1.1

Install the PCM ZIP directly with KiCad Manager → Plugin and Content Manager → Install from File. Restart KiCad, enable its IPC API in preferences, and launch BOM Studio from the plugin toolbar.

The interface runs locally in a wxPython desktop window, with an installed-browser fallback when the embedded runtime is unavailable. When launched from PCB Editor, its saved project opens automatically. For standalone use choose **Change project**. Review parts and missing fields, edit values or fitted/DNP status, set **BOM settings**, then **Export BOM**. **Save workspace** preserves staged edits; **Review & native sync** is the separate reviewed step that writes them to KiCad files. Five main navigation views cover daily work; **More tools** contains optional advanced workflows.

See [README.md](README.md) for desktop dependencies, the saved-native-data distinction, CLI examples and validation limits. See [help.html](help.html) for an offline quick reference.
