"""Fabricator-profile audits and deterministic release manifests."""

from __future__ import annotations

import hashlib
import json
import zipfile
import math
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class FabricatorProfile:
    name: str = "Demo standard capability"
    minimum_track_mm: float = 0.15
    minimum_clearance_mm: float = 0.15
    minimum_drill_mm: float = 0.20
    minimum_annular_ring_mm: float = 0.10
    maximum_via_aspect_ratio: float = 10.0
    maximum_layers: int = 12


@dataclass
class BoardMetrics:
    minimum_track_mm: float
    minimum_clearance_mm: float
    minimum_drill_mm: float
    minimum_annular_ring_mm: float | None
    maximum_via_aspect_ratio: float
    copper_layers: int
    minimum_exact_annular_ring_mm: float = float('inf')
    annular_ring_is_lower_bound: bool = False


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    item: str
    actual: str
    requirement: str


def audit_metrics(metrics: BoardMetrics, profile: FabricatorProfile) -> list[ReadinessCheck]:
    validate_profile(profile)
    checks = []
    def minimum(item: str, actual: float, required: float, unit: str = "mm") -> None:
        if actual == float('inf'):
            checks.append(ReadinessCheck('N/A',item,'No applicable objects',f'>= {required:g} {unit}'))
            return
        if actual is None:
            checks.append(ReadinessCheck('UNKNOWN',item,'Unsupported saved pad geometry',f'>= {required:g} {unit}'))
            return
        checks.append(ReadinessCheck("PASS" if actual >= required else "FAIL", item,
                                     f"{actual:g} {unit}", f">= {required:g} {unit}"))
    minimum("Minimum routed track", metrics.minimum_track_mm, profile.minimum_track_mm)
    minimum("Minimum copper clearance", metrics.minimum_clearance_mm, profile.minimum_clearance_mm)
    minimum("Minimum finished drill (pads and vias)", metrics.minimum_drill_mm, profile.minimum_drill_mm)
    ring_item="Minimum annular ring (plated pads and vias)";ring=metrics.minimum_annular_ring_mm;required=profile.minimum_annular_ring_mm
    if metrics.minimum_exact_annular_ring_mm < required:
        checks.append(ReadinessCheck('FAIL',ring_item,f'{metrics.minimum_exact_annular_ring_mm:g} mm',f'>= {required:g} mm'))
    elif ring is None:
        checks.append(ReadinessCheck('UNKNOWN',ring_item,'Unsupported saved pad geometry',f'>= {required:g} mm'))
    elif metrics.annular_ring_is_lower_bound:
        checks.append(ReadinessCheck('PASS' if ring >= required else 'UNKNOWN',ring_item,
                                     f'>= {ring:g} mm conservative lower bound',f'>= {required:g} mm'))
    else:
        minimum(ring_item,ring,required)
    checks.append(ReadinessCheck("PASS" if metrics.maximum_via_aspect_ratio <= profile.maximum_via_aspect_ratio else "FAIL",
                                 "Maximum via aspect ratio", f"{metrics.maximum_via_aspect_ratio:g}:1",
                                 f"<= {profile.maximum_via_aspect_ratio:g}:1"))
    checks.append(ReadinessCheck("PASS" if metrics.copper_layers <= profile.maximum_layers else "FAIL",
                                 "Copper layers", str(metrics.copper_layers), f"<= {profile.maximum_layers}"))
    return checks


def save_profile(path: str | Path, profile: FabricatorProfile) -> None:
    Path(path).write_text(json.dumps(asdict(profile), indent=2) + "\n", encoding="utf-8")


def load_profile(path: str | Path) -> FabricatorProfile:
    profile=FabricatorProfile(**json.loads(Path(path).read_text(encoding="utf-8")))
    validate_profile(profile)
    return profile


def validate_profile(profile):
    if not str(profile.name).strip():raise ValueError('Give the fabricator profile a name.')
    for key,value in asdict(profile).items():
        if key=='name':continue
        if isinstance(value,bool) or not math.isfinite(float(value)) or value<=0:
            raise ValueError('Profile limits must be positive finite numbers: '+key)
    if int(profile.maximum_layers)!=profile.maximum_layers:
        raise ValueError('Maximum layers must be a whole number.')


def sexpr_tokens(text):
    """Whitespace-independent comparison preserving every serialized token."""
    return re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+',text)


def saved_metrics(board_bytes,project_bytes):
    """Read the exact saved inputs supplied to CLI, without a live SWIG object.

    Via aspect ratios conservatively use full board thickness. Annular ring is
    reported as unknown when a saved padstack cannot be bounded safely.
    """
    tokens=sexpr_tokens(board_bytes.decode('utf-8-sig'));stack=[];root=None
    for token in tokens:
        if token=='(':
            node=[]
            if stack:stack[-1].append(node)
            stack.append(node)
        elif token==')':
            if not stack:raise ValueError('Malformed saved PCB.')
            node=stack.pop()
            if not stack:
                if root is not None:raise ValueError('Multiple saved PCB roots.')
                root=node
        elif stack:stack[-1].append(token)
        else:raise ValueError('Malformed saved PCB.')
    if stack or not root or root[0]!='kicad_pcb':raise ValueError('Expected a saved KiCad PCB.')
    def children(node,name):return [x for x in node if isinstance(x,list) and x and x[0]==name]
    def number(node,name):
        found=children(node,name)
        if len(found)!=1 or len(found[0])!=2:raise ValueError('Saved PCB is missing an unambiguous '+name+'.')
        value=float(found[0][1])
        if not math.isfinite(value) or value<=0:raise ValueError('Saved PCB has invalid '+name+'.')
        return value
    general=children(root,'general');layers=children(root,'layers')
    if len(general)!=1 or len(layers)!=1:raise ValueError('Saved PCB has no general/layer settings.')
    thickness=number(general[0],'thickness')
    count=sum(1 for layer in layers[0] if isinstance(layer,list) and len(layer)>=3 and layer[2] in ('signal','power','mixed','jumper'))
    if count<1:raise ValueError('Saved PCB has no copper layers.')
    tracks=[number(node,'width') for name in ('segment','arc') for node in children(root,name)]
    vias=children(root,'via')
    drills=[number(via,'drill') for via in vias]
    via_drills=list(drills)
    exact_rings=[];lower_ring_bounds=[];rings_unknown=False
    for via,drill in zip(vias,drills):
        if children(via,'padstack'):
            rings_unknown=True
        else:exact_rings.append((number(via,'size')-drill)/2)
    for footprint in children(root,'footprint')+children(root,'module'):
        for pad in children(footprint,'pad'):
            if len(pad)<4 or pad[2] not in ('thru_hole','np_thru_hole'):continue
            hole=children(pad,'drill');size=children(pad,'size')
            if len(hole)!=1:raise ValueError('A drilled pad is missing its unambiguous drill dimensions.')
            hole=hole[0];oval=len(hole)>1 and hole[1]=='oval';offset=2 if oval else 1
            try:
                dx=float(hole[offset]);dy=float(hole[offset+1]) if oval else dx
            except (IndexError,ValueError) as exc:raise ValueError('Invalid pad drill dimensions.') from exc
            if not all(math.isfinite(v) and v>0 for v in (dx,dy)):raise ValueError('Pad drill dimensions must be positive and finite.')
            drills.append(min(dx,dy))
            if pad[2]=='np_thru_hole':continue
            if len(size)!=1 or len(size[0])!=3:raise ValueError('Plated pad size is missing.')
            sx,sy=map(float,size[0][1:])
            offsets=children(hole,'offset')
            if len(offsets)>1 or (offsets and len(offsets[0])!=3):raise ValueError('Ambiguous drill offset.')
            ox,oy=map(float,offsets[0][1:]) if offsets else (0.,0.)
            if not all(math.isfinite(v) for v in (sx,sy,ox,oy)) or min(sx,sy)<=0:raise ValueError('Invalid plated pad size or drill offset.')
            dimensions=[(sx,sy)]
            supported=pad[3] in ('circle','oval','rect','roundrect')
            if pad[3]=='custom':
                options=children(pad,'options')
                anchors=children(options[0],'anchor') if len(options)==1 else []
                supported=len(anchors)==1 and len(anchors[0])==2 and anchors[0][1] in ('circle','rect')
                if supported and anchors[0][1]=='circle' and not math.isclose(sx,sy,rel_tol=0,abs_tol=1e-12):supported=False
            padstacks=children(pad,'padstack')
            if padstacks:
                supported=supported and len(padstacks)==1
                for layer in children(padstacks[0],'layer'):
                    shapes=children(layer,'shape');sizes=children(layer,'size')
                    if len(shapes)!=1 or len(shapes[0])!=2 or shapes[0][1] not in ('circle','oval','rect','roundrect') or len(sizes)!=1 or len(sizes[0])!=3:
                        supported=False;continue
                    try:dimensions.append(tuple(map(float,sizes[0][1:])))
                    except ValueError:supported=False
                    if shapes and len(shapes[0])==2 and shapes[0][1]=='circle' and len(sizes)==1 and len(sizes[0])==3:
                        try:
                            if not math.isclose(float(sizes[0][1]),float(sizes[0][2]),rel_tol=0,abs_tol=1e-12):supported=False
                        except ValueError:pass
            if not supported or any(not all(math.isfinite(v) and v>0 for v in dims) for dims in dimensions):
                rings_unknown=True;continue
            # Bounding dimensions alone overestimate corner clearance for oblique
            # offsets on curved pads; subtract the full offset magnitude instead.
            measured=[min((px-dx)/2,(py-dy)/2)-math.hypot(ox,oy) for px,py in dimensions]
            if pad[3]=='custom' or ox or oy:lower_ring_bounds.extend(measured)
            else:exact_rings.extend(measured)
    project=json.loads(project_bytes.decode('utf-8-sig'))
    clearance=project.get('board',{}).get('design_settings',{}).get('rules',{}).get('min_clearance')
    if clearance is None or not math.isfinite(float(clearance)) or float(clearance)<0:
        raise ValueError('Save the project minimum clearance rule before auditing.')
    exact_annular=min(exact_rings,default=float('inf'))
    lower_annular=min(lower_ring_bounds,default=float('inf'))
    annular=None if rings_unknown else min(exact_annular,lower_annular)
    return BoardMetrics(min(tracks,default=float('inf')),float(clearance),min(drills,default=float('inf')),
                        annular,max((thickness/d for d in via_drills),default=0),count,exact_annular,
                        lower_annular < exact_annular)


def gate_key(files,profile,jobset,live_text):
    validate_profile(profile)
    payload={'files':{str(name):hashlib.sha256(data).hexdigest() for name,data in files.items()},
             'profile':asdict(profile),'jobset':str(jobset),
             'live':hashlib.sha256(json.dumps(sexpr_tokens(live_text)).encode()).hexdigest()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def build_release(output_zip: str | Path, files: list[str | Path], checks: list[ReadinessCheck],
                  tool_version: str, *, expected_hashes=None, base_directory=None, evidence=None) -> dict:
    if not checks:raise ValueError('Release requires a completed board audit.')
    failed = [check.item for check in checks if check.status not in ("PASS", "N/A")]
    if failed: raise ValueError("Release blocked by failed or unknown checks: " + ", ".join(failed))
    source_files = [Path(path) for path in files]
    if not source_files:raise ValueError('Release has no source files.')
    base=Path(base_directory).resolve() if base_directory else None
    payloads={}
    for source in source_files:
        name=source.resolve().relative_to(base).as_posix() if base else source.name
        if name.casefold() in {key.casefold() for key in payloads} or name=='wayricad-release-manifest.json':
            raise ValueError('Duplicate release archive member: '+name)
        payloads[name]=source.read_bytes()
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()}
    if expected_hashes is not None and hashes!=expected_hashes:
        raise ValueError('Release inputs changed after verification. Repeat the audit and checks.')
    manifest = {"tool": "WayriCAD Manufacturing Readiness Manager", "version": tool_version,
                "files": [], "checks": [asdict(check) for check in checks]}
    if evidence is not None:manifest['verification']=evidence
    for name,data in sorted(payloads.items()):
        manifest["files"].append({"name":name,"size":len(data),"sha256":hashes[name]})
    destination = Path(output_zip); destination.parent.mkdir(parents=True, exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.wayricad-release-',suffix='.zip',dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary,"w",zipfile.ZIP_DEFLATED) as archive:
            content=dict(payloads)
            content['wayricad-release-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode('utf-8')
            for name,data in sorted(content.items()):
                info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,data)
        os.replace(temporary,destination)
    finally:
        if Path(temporary).exists():Path(temporary).unlink()
    return manifest
