"""Invoked only in FreeCAD Python; reads STEP geometry, never executes CAD macros."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys

# Official Windows FreeCAD keeps extension modules in ../lib, separately from
# its bundled Python. Keep DLL-directory handles alive throughout inspection.
_dll_handles=[]
if os.name=='nt':
    root=Path(sys.executable).resolve().parent.parent
    if (root/'lib'/'Part.pyd').is_file() and (root/'bin'/'FreeCAD.pyd').is_file():
        sys.path.insert(0,str(root/'lib'))
        for directory in (root/'bin',root/'lib'):
            _dll_handles.append(os.add_dll_directory(str(directory)))


def inspect(path):
    import FreeCAD
    import Part
    shape=Part.Shape();shape.read(str(path))
    if shape.isNull() or not shape.isValid() or not shape.Solids:raise ValueError('STEP must contain valid closed solids')
    bounds=shape.BoundBox
    dimensions=[bounds.XLength,bounds.YLength,bounds.ZLength]
    volume=sum(solid.Volume for solid in shape.Solids)
    if not all(math.isfinite(v) and v>0 for v in dimensions+[volume]):raise ValueError('Degenerate STEP dimensions or volume')
    vertices,faces=shape.tessellate(max(dimensions)/60)
    if len(vertices)>200000 or len(faces)>200000:raise ValueError('STEP preview exceeds 200,000 mesh entities')
    return dict(source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                engine='FreeCAD '+'.'.join(FreeCAD.Version()[:3]),solid_count=len(shape.Solids),
                bounding_dimensions_mm=dimensions,solid_volume_mm3=volume,
                vertices_mm=[[p.x,p.y,p.z] for p in vertices],triangles=faces,
                limitation='Outside bounds and geometric solid volume do not determine effective magnetic area/path/gap. No FEA mesh, materials, winding excitation or field solve is inferred.')


if __name__=='__main__':
    try:Path(sys.argv[2]).write_text(json.dumps(inspect(Path(sys.argv[1])),allow_nan=False),encoding='utf-8')
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)
