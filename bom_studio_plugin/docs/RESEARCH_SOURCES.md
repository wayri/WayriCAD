# Official interface references checked for this implementation

Checked while preparing this preview, 2026-09-09. The implementation is original code; these references establish file/API semantics, not runtime validation.

- KiCad IPC addon developer guide, plugin locations, manifest/runtime behavior and evolving KiCad 11/headless capabilities: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/
- IPC plugin manifest schema: https://go.kicad.org/api/schemas/v1
- KiCad 10 Schematic Editor manual, design variants, DNP/BOM/position attributes and schematic-to-PCB propagation: https://docs.kicad.org/10.0/en/eeschema/eeschema.html
- Alternate manual locale whose variant section was available during research: https://docs.kicad.org/10.0/zh/eeschema/eeschema.html
- KiCad 10 CLI manual, native BOM variant and formatting flags: https://docs.kicad.org/10.0/en/cli/cli.html
- KiCad 10 PCB Editor manual, project text-variable sharing: https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- KiCad 10 branch schematic formatter, exact field/instance/variant and hidden-field serialization: https://gitlab.com/kicad/code/kicad/-/raw/10.0/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr.cpp
- KiCad 10 branch parser, including pre/post-20260306 variant in_bom inversion: https://gitlab.com/kicad/code/kicad/-/raw/10.0/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_parser.cpp
- KiCad 10 schematic format history: https://gitlab.com/kicad/code/kicad/-/raw/10.0/eeschema/sch_file_versions.h
- Schematic settings, variant catalogue and BOM preset persistence: https://gitlab.com/kicad/code/kicad/-/raw/10.0/eeschema/schematic_settings.cpp
- Project settings and ordinary single top-level-sheet migration: https://gitlab.com/kicad/code/kicad/-/raw/10.0/common/project/project_file.cpp
- Siemens Xpedition overview, used to avoid overstating enterprise equivalence: https://www.siemens.com/en-us/products/pcb/xpedition/
- Siemens variant-management discussion: https://blogs.sw.siemens.com/electronic-systems-design/2022/10/28/variant-management/

Facts from documentation and source were translated into conservative feature gates. A parser test against synthetic fixtures is not equivalent to loading the output in KiCad. No supplier-data entitlement, Xpedition integration or Siemens/KiCad endorsement is implied.


## 0.2-specific primary sources

- KiCad 10 Schematic Editor manual: Symbol Fields Table virtual columns; Symbol Field Name Templates; BOM presets; variables used as field names and their generated-value semantics: https://docs.kicad.org/10.0/en/eeschema/eeschema.html
- Native project field-name persistence (`schematic.drawing.field_names` records with name/visible/url): https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/eeschema/schematic_settings.cpp
- Exact generated-field-name detection and expression handling: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/common/common.cpp
- Generated name/value coupling and shown-name behavior: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/eeschema/sch_field.cpp
- JLCPCB's KiCad BOM guide and column headings, checked 2026-09-09: https://jlcpcb.com/help/article/how-to-generate-the-bom-and-centroid-file-from-kicad

These source checks informed explicit guards; they do not substitute for running KiCad itself. The generic XML is an original WayriCAD BOM schema, not a claim of conformance to a board-manufacturing or materials-declaration standard. Template definitions contain no copied KiCad/Siemens implementation or binary assets.


## 0.3 official sources checked on 9 September 2026

- DigiKey myLists BOM maintenance: https://www.digikey.com/en/help-support/place-an-order/build-a-bom
- DigiKey myLists price/availability: https://www.digikey.com/en/help-support/place-an-order/price-and-availability
- Mouser FORTE free account-based tool: https://www.mouser.in/en/bomtool/
- Mouser configurable BOM exports: https://www.mouser.com/help/tools/manage-your-saved-boms/
- Mouser BOM match review/export: https://www.mouser.com/help/tools/view-bom-matches/
- DigiKey APIs at no cost: https://www.digikey.in/en/resources/api-solutions
- DigiKey developer registration/authentication: https://developer.digikey.com/documentation
- Mouser free API offerings: https://www.mouser.in/api-solutions/
- Mouser authenticated Search API: https://www.mouser.com/en/api-search/
- KiCad library naming conventions (heuristic interpretation, not qualification): https://klc.kicad.org/footprint/f2/f2.1/ and https://klc.kicad.org/footprint/f3/f3.4.html

These sources describe website/API capabilities; they are not evidence that the new extension was tested against live pages. No API credentials, paid aggregator, scraping bypass or guaranteed live stock are supplied. Supplier formats, services and access policies can change.


## v0.4 primary-source verification (9 September 2026)

- KiCad 10 PCB Editor manual, native cross-selection and editor preferences: https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- KiCad 10 Manager manual, Job Sets / Special Execute Command / JOBSET_OUTPUT_WORK_PATH: https://docs.kicad.org/10.0/en/kicad/kicad.html
- KiCad 10 CLI manual, jobset run and destination IDs: https://docs.kicad.org/10.0/en/cli/cli.html
- Official Python Board APIs (selection, footprint linkage): https://docs.kicad.org/kicad-python-main/board.html
- Official Python KiCad APIs (get_schematic marked KiCad 11; RunAction explicitly unstable): https://docs.kicad.org/kicad-python-main/kicad.html
- Official SDK package 0.8.0: https://pypi.org/project/kicad-python/0.8.0/
- Official plugin manifest/runtime requirements: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/

The development API documentation includes future-host capabilities; the plugin does not infer KiCad 10 support from a main-branch method's existence. KiCad 10 source contracts were also inspected via the KiCad source mirror's 10.0 branch: common/jobs/jobset.cpp, common/jobs/job_special_execute.cpp, common/jobs/jobs_output_folder.cpp, api/proto/common/types/base_types.proto, api/proto/board/board_types.proto, api/proto/common/commands/editor_commands.proto, pcbnew/api/api_handler_pcb.cpp, common/tool/selection_tool.cpp, pcbnew/cross-probing.cpp, common/tool/actions.cpp and pcbnew/footprint.cpp.

Base: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/

These sources support the adapter design and native JSON/protobuf contracts. They are not evidence that this distribution has run in an actual KiCad host. Native relay/focus/launch and job-set collection remain target-system acceptance items.
