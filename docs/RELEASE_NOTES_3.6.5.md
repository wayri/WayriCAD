# WayriCAD 3.6.5 release notes

Project Fusion is included in the WayriCAD source archive and Python wheel for
the first time. Its independent KiCad PCM package is updated from 0.9.3 to
0.9.4. The other 17 independently installable PCM packages remain at 3.6.4;
their published ZIPs are unchanged.

Fusion 0.9.4 corrects PCB-to-schematic association paths so native schematic
updates can recognize imported footprints. During source-copy repair it keeps
routed copper for equivalent numbered-pad connections and safe net renames.
Changed connections with ambiguous copper now stop for review instead of
removing an entire net's tracks, vias, or zones. Existing generated projects
are not migrated automatically, and installation cannot restore copper removed
by an older version.

Install `WayriCAD-project-fusion-0.9.4-PCM.zip` through KiCad 10 Plugin and
Content Manager, then restart PCB Editor. Fusion appears in **Tools → External
Plugins**. Its package identifier remains `org.wayri.projectfusion`; it uses
KiCad's native SWIG action loader and retains its MIT license and testing
status. The [Fusion guide](../project_fusion_plugin/README.md) describes its
review and offline apply workflow.

The [Fusion validation record](audits/FUSION_0_9_4_BETA.md) covers source and
isolated PCM tests, native saved-file association/copper fixtures and known
limits. Live editor Update PCB, installed GUI restart and connected IPC
transactions were not qualified by those tests. Run native ERC and DRC on each
generated project before fabrication.
