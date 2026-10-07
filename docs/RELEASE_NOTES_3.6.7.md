# WayriCAD 3.6.7 release notes

Project Fusion is updated as an independent KiCad 10 PCM package at version
0.9.5. Other PCM packages retain their published versions and ZIPs.

Fusion's PCB and schematic preview canvases now fit saved design geometry when
their tabs first open. Source preflight shows a decision for every issue and can
stage safe source-copy repairs, including restoring PCB references when a unique
schematic association proves the intended reference. Board-only copper can be
reviewed as an advisory or ignored; ambiguous identities and electrical conflicts
remain blocking. All repairs operate on a separate copy and require a fresh
preview before import.

A saved external project or subsheet can be imported with a persistent source
link. The linked-update review now offers a suggestion for each source change and
destination conflict. Ignoring a change defers that design's entire update; it
does not silently omit one value, footprint or connection. Native KiCad 10 tests
cover inherited Value and MPN fields, selected Footprint and routed placement,
with stable surviving symbol/PCB identities, source hashes and candidate checks.
The optional **Update schematic; keep target placement and routing** mode
preserves a locally moved/rerouted imported block while updating its schematic.
A compatible replacement footprint can bring in its new pad and body geometry at
the retained target position. Changed pad numbers, ambiguous net connections or
new DRC/unconnected findings stop the candidate for manual review.
**Update PCB layout; keep target schematic** is the converse reviewed mode: it
imports the source block's changed placement and routing while preserving the
target schematic and its current Value/BOM fields. It requires unchanged linked
symbol identity and electrical partitions; a mismatched footprint assignment or
new native validation finding stops the candidate.
Electrical rewiring and changes to linked-owned destination content still require
explicit review and may stop the update.

Mixed-stack imports and merges keep the source bottom copper and bottom-side
components on the output `B.Cu`. The source's internal copper follows its
physical order; only native full-stack `F.Cu`-to-`B.Cu` through vias are
accepted. Conversion changes the dielectric and drill environment, so review
the reported native DRC findings, clearances, impedance and fabrication limits.

Install `WayriCAD-project-fusion-0.9.5-PCM.zip` through KiCad 10 Plugin and
Content Manager and restart PCB Editor. Whole-project import needs matching
`.kicad_pro`, root `.kicad_sch` and `.kicad_pcb` files. Schematic-only subsheet
extraction can omit the source board. Offline application requires closed source
and target editors and creates a backup. The plugin remains a testing release;
other operating systems, all installed-editor workflows and manufacturing
qualification remain separate acceptance checks.
