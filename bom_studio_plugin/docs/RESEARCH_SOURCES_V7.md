# v0.7 primary-source references

Checked 9 September 2026. Documentation/source review is not native-host execution. Public source code is referenced for interoperability; no KiCad binaries, font files or manufacturer CAD assets are bundled.

* KiCad 10 PCB Editor, embedded resources, model references and path configuration: https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
* KiCad S-expression grammar, coordinates, properties, symbol units and footprint/model fields: https://dev-docs.kicad.org/en/file-formats/sexpr-intro/
* KiCad embedded resource serialization/decompression/checksum logic: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/common/embedded_files.cpp and https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/include/embedded_files.h
* Native symbol property visibility parsing: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_parser.cpp
* Symbol serialization: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_lib_cache.cpp
* Pad relative/native angle conventions: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/pcbnew/pad.cpp and https://raw.githubusercontent.com/KiCad/kicad-source-mirror/master/libs/kimath/src/trigo.cpp
* Optional OpenCascade Python wrapper, exact tested release: https://pypi.org/project/cadquery-ocp/7.9.3.1.1/
* Optional portable Zstandard decoder, exact pinned release: https://pypi.org/project/zstandard/0.25.0/

The private preview implementation uses its own bounded SVG/mesh readers and drawing code, not a scraped KiCad viewer. MurmurHash3 math is the public-domain algorithm; modern outputs were independently checked against the compiled MurmurHash3_x64_128 implementation in the development environment's murmurhash module, at 13 lengths (including block/tail boundaries). Only expected hashes and original test inputs are distributed, not that binary. Legacy embedded checksums are reproduced from the documented/source-reviewed KiCad behavior and synthetic fixtures; actual KiCad-generated file/host validation remains outstanding.

VRML/STL/OBJ originals are parsed as data. STEP/IGES/BREP uses the separately installed optional OCP library. Third-party modules retain their own licenses. Synthetic WRL/STEP models in examples/assets were authored for this package and are not measured or qualified manufacturer data.
