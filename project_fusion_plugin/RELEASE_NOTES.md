# Wayri Project Fusion 0.9.4 beta 1

Testing release, 3 October 2026. KiCad 10; legacy SWIG entry point.

- Correct PCB-to-schematic association paths so native updates can reuse the
  imported footprints. Validate against unmodified native exported paths.
- Keep schematic instance paths and PCB associations distinct throughout create,
  insertion, extraction and linked updates, preserving stable item identities.
- Replace whole-net copper deletion during source-copy repair with a blocking
  review when changed connections make existing copper ambiguous. Preserve
  equivalent pin partitions and safe net renames.
- Add generic regressions for native links, geometry/group preservation,
  copper-bearing connection changes, and unchanged source files.

The association fix follows KiCad 10's
[root-free sheet-path export](https://github.com/KiCad/kicad-source-mirror/blob/10.0/eeschema/sch_sheet_path.cpp#L421)
and [literal updater comparison](https://github.com/KiCad/kicad-source-mirror/blob/10.0/pcbnew/netlist_reader/board_netlist_updater.cpp#L1955).
Native XML regression checks are independent of Fusion's conversion helper.

Existing projects are not automatically migrated, and copper removed by older
releases is not recreated by installation. Use original sources and a reviewed
candidate. This release is not manufacturing approval. See TEST_REPORT.md.

Install WayriCAD-project-fusion-0.9.4-PCM.zip using KiCad Plugin and Content Manager,
then restart PCB Editor. The Source ZIP is for source review/development.
The package identifier remains org.wayri.projectfusion. No IPC manifest is added.

The public 0.9.3 assets remain unchanged. This beta also retains the current
upstream CLI import guard, installation guide and help resources. The stable
PCM feed is not promoted by this prerelease.
