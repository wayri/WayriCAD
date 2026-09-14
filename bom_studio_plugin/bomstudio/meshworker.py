"""Isolated optional OpenCascade tessellation; invoked only with owned temp files."""
from pathlib import Path
import json
import sys

def run(file):
    from .meshpreview import unpack,vrml,stl,obj
    raw,ext=unpack(file.read_bytes(),file.suffix.lower())
    if ext=='.wrl':return vrml(raw)
    if ext=='.stl':return stl(raw)
    if ext=='.obj':return obj(raw)
    if ext!=file.suffix.lower():
        file=file.with_name('unpacked'+ext);file.write_bytes(raw)
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IGESControl import IGESControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopoDS import TopoDS,TopoDS_Shape
        from OCP.TopLoc import TopLoc_Location
        from OCP.BRep import BRep_Tool,BRep_Builder
        from OCP.BRepTools import BRepTools
    except ImportError as exc:
        raise ValueError('Optional STEP/IGES/BREP preview engine unavailable. Install requirements-preview.txt in the Python running WayriCAD. Capture/download/VRML/STL previews do not need it.') from exc
    from .meshpreview import Mesh
    if file.suffix in ('.step','.stp'):
        # Refuse external-document references; never follow a model into arbitrary
        # filesystem locations. All files in this worker are owned temporary data.
        if b'EXTERNAL_SOURCE' in file.read_bytes().upper() or b'EXTERNALLY_DEFINED_REPRESENTATION' in file.read_bytes().upper():raise ValueError('External STEP document references are unsupported; store a self-contained STEP assembly.')
        reader=STEPControl_Reader()
    elif file.suffix in ('.iges','.igs'):reader=IGESControl_Reader()
    else:reader=None
    if reader:
        if reader.ReadFile(str(file))!=IFSelect_RetDone:raise ValueError('OpenCascade could not read this model.')
        reader.TransferRoots();shape=reader.OneShape()
    else:
        shape=TopoDS_Shape()
        if not BRepTools.Read_s(shape,str(file),BRep_Builder()):raise ValueError('Invalid BREP.')
    if shape.IsNull():raise ValueError('Model has no transferable shape.')
    mesher=BRepMesh_IncrementalMesh(shape,.08,False,.25,False)
    if not mesher.IsDone():raise ValueError('Tessellation did not complete.')
    mesh=Mesh();explorer=TopExp_Explorer(shape,TopAbs_FACE);missing=0
    while explorer.More():
        face=TopoDS.Face_s(explorer.Current());loc=TopLoc_Location();tri=BRep_Tool.Triangulation_s(face,loc)
        if tri is None:missing+=1
        else:
            transform=loc.Transformation()
            for i in range(1,tri.NbTriangles()+1):
                inds=list(tri.Triangle(i).Get())
                if face.Orientation()==TopAbs_REVERSED:inds[1],inds[2]=inds[2],inds[1]
                coords=[]
                for j in inds:
                    p=tri.Node(j).Transformed(transform);coords.append([p.X(),p.Y(),p.Z()])
                mesh.triangle(*coords,[.64,.69,.77])
        explorer.Next()
    mesh.warnings.append('OpenCascade inspection mesh: 0.08 mm linear / 0.25 rad angular tolerance. STEP/IGES material colors and annotations are not rendered.')
    if missing:mesh.warnings.append(str(missing)+' faces had no triangulation; preview is incomplete.')
    return mesh.result(file.suffix[1:].upper())

if __name__=='__main__':
    out=Path(sys.argv[2])
    try:
        # Advisory process resource limits on POSIX; Windows still has timeout/
        # triangle/output bounds but no equivalent memory job object in this build.
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(55,60))
            resource.setrlimit(resource.RLIMIT_AS,(3*1024**3,3*1024**3))
        except (ImportError,ValueError,OSError):pass
        result=run(Path(sys.argv[1]))
    except Exception as exc:result={'error':str(exc)}
    out.write_text(json.dumps(result,allow_nan=False,separators=(',',':')))
