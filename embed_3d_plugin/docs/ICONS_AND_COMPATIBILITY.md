# WayriCAD Embed3D 0.4.1 — icon and package compatibility

Reviewed 10 September 2026. This release targets **KiCad 10.0.x**, with **SWIG ActionPlugin** runtime and **testing** status. It is not IPC, not a KiCad 11 release and not published/certified by the official KiCad repository.

The approved artwork is unchanged from 0.3.0: 64×64 RGBA PNG PCM icon; 24×24 PNG light/dark toolbar paths; multi-resolution dialog header/window icons. The original master is retained in the Source ZIP. No image library, font file or remote resource is required at runtime. Large branding text is not intended to be legible at toolbar scale; tooltip/action names provide identification.

The new default entrypoint creates `WorkspaceDialog`. The old `EmbedDialog` remains only for explicitly selected advanced library/live-model workflows. Both reuse the local icon helper and native system theme. No fabricated or rendered mockup is provided as evidence of real wx/KiCad execution.

## Package contract checked

- `metadata.json` at ZIP root; `resources/icon.png`; Python modules directly in `plugins/`.
- `$schema` references PCM v2 and the required `resources` object is present.
- Existing local identifier `local.embed_3d_plugin`, version `0.4.1`, `runtime: swig`, status `testing`, KiCad minimum/maximum branch `10.0`.
- New `workspace.py` and `workspace_ui.py` required by the validator, alongside all earlier backend modules.
- No nested `plugins/embed_3d_plugin` wrapper, Python caches, duplicate/unsafe archive paths, remote downloads, or self-referential download checksum fields inside the ZIP.
- Original icons, sizes, actual PNG/ICO decoding, packaged/source byte comparisons and checksums.

The build uses package-specific validation rules, not a claim of complete official-schema validation. `python build_packages.py <destination> --schema <official-schema.json>` supports full validation when a local official schema is supplied. KiCad installation itself remains untested in this environment.

## Native implementation boundaries

Models use native embedded payloads and model URIs. PCB/schematic reusable library archives hold actual bytes, while editable library lookup uses native filesystem `.pretty` / `.kicad_sym` files and project tables. Schematic native caches and placed board geometry are retained. No new embedded-filesystem library backend is claimed.

The main workspace processes saved designs into new copies. It does not update open editor buffers or install a Schematic Editor toolbar. Footprint normalization and detached validation use the existing native bridge. Real runtime/parser/rendering, GUI event and high-DPI checks remain pending; see `TEST_REPORT.md`.

## Primary references

- PCM package layout, icons and runtime: https://dev-docs.kicad.org/en/addons/index.html
- KiCad PCB Python API: https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/index.html
- Native schematic caches: https://docs.kicad.org/10.0/en/eeschema/eeschema.html
- wx native table model contracts: https://docs.wxpython.org/wx.dataview.DataViewModel.html

The glossy approved icon uses third-party PNG integration. It is not represented as conforming to KiCad's separate flat-SVG contributor artwork guidelines or as adding support for every extension printed in the artwork.
