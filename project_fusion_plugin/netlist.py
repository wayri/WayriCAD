"""Independent KiCad CLI validation. Never infer automatic net names."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from .model import MergeError
from .schematic import canonical_path, remap_footprint_id


@dataclass
class Netlist:
    components: dict = field(default_factory=dict)
    nets: dict = field(default_factory=dict)
    pins: dict = field(default_factory=dict)

    @classmethod
    def read(cls,path,root_uuid=None):
        p=Path(path)
        if p.stat().st_size>256*1024*1024:
            raise MergeError('Netlist exceeds 256 MiB safety limit.')
        data=p.read_bytes()
        if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
            raise MergeError('DTD/entity declarations are not permitted in netlists.')
        try:
            root=ET.fromstring(data)
        except ET.ParseError as e:
            raise MergeError(f'Invalid KiCad XML netlist: {e}') from e
        if root.tag!='export':
            raise MergeError('Expected a KiCad XML netlist with <export> root.')
        result=cls()
        for comp in root.findall('./components/comp'):
            ref=comp.get('ref','')
            if not ref or ref in result.components:
                raise MergeError(f'Duplicate/missing component reference in exported netlist: {ref!r}')
            sp=comp.find('sheetpath')
            sheet=sp.get('tstamps','') if sp is not None else ''
            # Native XML sheetpath stamps are the PCB association authority.
            # Schematic instance records include the root UUID, but neither
            # the XML exporter nor Update PCB from Schematic includes it here.
            if root_uuid:
                if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',root_uuid):
                    raise MergeError('Invalid owning root UUID for native netlist.')
            ts=comp.find('tstamps')
            stamps=' '.join(ts.itertext()) if ts is not None else ''
            if not stamps:
                stamps=comp.findtext('tstamp','')
            uuids=re.findall(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',stamps)
            paths={canonical_path(sheet+'/'+u) for u in uuids}
            result.components[ref]={'footprint':comp.findtext('footprint',''), 'paths':paths, 'value':comp.findtext('value','')}
        for net in root.findall('./nets/net'):
            name=net.get('name','')
            # XML unescapes '/' in automatic pin-derived names, but KiCad's
            # PCB/parity representation keeps {slash}. Hierarchy separators
            # outside Net-(...) remain literal '/'.
            name=re.sub(r'Net-\(([^)]*)\)',lambda match:'Net-('+match.group(1).replace('/','{slash}')+')',name)
            if name in result.nets:
                raise MergeError(f'Duplicate net name in exported netlist: {name}')
            endpoints=set()
            for node in net.findall('node'):
                ep=(node.get('ref',''),node.get('pin',''))
                if not all(ep):
                    raise MergeError('Missing reference/pin in exported netlist.')
                if ep in result.pins and result.pins[ep]!=name:
                    raise MergeError(f'Pin {ep} appears in multiple schematic nets.')
                endpoints.add(ep)
                result.pins[ep]=name
            result.nets[name]=endpoints
        return result


def find_cli(explicit=''):
    candidates=[]
    if explicit:
        candidates.append(Path(explicit).expanduser())
    else:
        found=shutil.which('kicad-cli')
        if found:
            candidates.append(Path(found))
        if os.name=='nt':
            for base in filter(None,(os.environ.get('ProgramFiles'),os.environ.get('ProgramW6432'))):
                root=Path(base)/'KiCad'
                if root.is_dir():
                    candidates.extend(sorted(root.glob('10*/bin/kicad-cli.exe'),reverse=True))
            try:
                import pcbnew
                for p in Path(pcbnew.__file__).parents:
                    candidates += [p/'bin/kicad-cli.exe',p/'kicad-cli.exe']
            except ImportError:
                pass
        else:
            candidates += [Path('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'), Path('/usr/bin/kicad-cli')]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise MergeError('KiCad 10 kicad-cli was not found. Browse to the executable installed with KiCad (on Windows: C:\\Program Files\\KiCad\\10.0\\bin\\kicad-cli.exe).')


class KiCadCLI:
    def __init__(self,path='',log=lambda m:None):
        self.path=find_cli(path)
        self.log=log
        self.commands=[]
        version=self.run(['version'],timeout=30).strip()
        if not re.search(r'\b10\.\d+',version):
            raise MergeError(f'This release requires KiCad 10, not: {version}')
        self.version=version

    def run(self,args,cwd=None,timeout=600):
        cmd=[self.path,*map(str,args)]
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
        try:
            proc=subprocess.run(cmd,cwd=str(cwd) if cwd else None,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',timeout=timeout,
                creationflags=creationflags,shell=False)
        except (OSError,subprocess.TimeoutExpired) as e:
            raise MergeError(f'KiCad CLI failed: {e}') from e
        self.commands.append({'argv':cmd,'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
        if proc.returncode:
            if proc.returncode in (3221225477,-1073741819):
                raise MergeError('KiCad CLI crashed with Windows access violation 0xC0000005 while running '+
                                 ' '.join(map(str,args[:4]))+'. Native validation could not complete. '
                                 'Verify that the standalone kicad-cli version command succeeds, then preview again. '
                                 'Windows Application crash diagnostics identify the faulting KiCad module.')
            raise MergeError(f'KiCad CLI returned {proc.returncode} for {" ".join(map(str,args[:4]))}:\n{proc.stderr[-4000:]}\n{proc.stdout[-4000:]}')
        return proc.stdout

    def export_netlist(self,schematic,destination,variant=None):
        self.log(f'KiCad netlist check: {Path(schematic).name}')
        args=['sch','export','netlist','--format','kicadxml','--output',destination]
        if variant not in (None,'<Default>'):
            args.extend(['--variant',variant])
        self.run([*args,schematic],cwd=Path(schematic).parent)
        if not Path(destination).is_file():
            raise MergeError('KiCad reported success but did not create the requested netlist.')
        from . import sexpr as sx
        return Netlist.read(destination,root_uuid=sx.value(sx.load(Path(schematic)),'uuid'))

    def drc(self,pcb,destination):
        self.log('KiCad: refill zones and check schematic/PCB parity.')
        self.run(['pcb','drc','--format','json','--schematic-parity','--refill-zones','--save-board','--output',destination,pcb],cwd=Path(pcb).parent)
        import json
        result=json.loads(Path(destination).read_text(encoding='utf-8-sig'))
        if 'schematic_parity' not in result:
            raise MergeError('KiCad DRC report has no schematic_parity field; validation cannot be certified with this CLI build.')
        if result['schematic_parity']:
            first=result['schematic_parity'][0]
            raise MergeError(f'KiCad reported schematic/PCB parity errors; output was not published. First finding: {first.get("description",first)}')
        return result


def compare_netlists(sources,merged):
    """Exact electrical partitions: catches both net splitting and accidental joins."""
    expected_refs=set()
    for source in sources:
        original=source.xml
        expected_refs.update(source.ref_map[ref] for ref in original.components)
        for ref,comp in original.components.items():
            target=source.ref_map.get(ref)
            if target not in merged.components:
                raise MergeError(f'{source.alias}: component {ref} → {target} missing from combined netlist.')
            if merged.components[target].get('value','')!=comp.get('value',''):
                raise MergeError(f'{source.alias}: resolved component value changed unexpectedly on {target}. Check project variables and structured field references.')
            expected_fp=remap_footprint_id(comp['footprint'],source)
            if merged.components[target]['footprint']!=expected_fp:
                raise MergeError(f'{source.alias}: footprint assignment changed unexpectedly on {target}.')
        for old_name,endpoints in original.nets.items():
            if not endpoints:
                continue
            expected={(source.ref_map[ref],pin) for ref,pin in endpoints}
            missing=expected-set(merged.pins)
            if missing:
                raise MergeError(f'{source.alias}: missing pins after merge: {sorted(missing)[:5]}')
            names={merged.pins[ep] for ep in expected}
            if len(names)!=1:
                raise MergeError(f'{source.alias}: source net {old_name!r} was split by the merge.')
            new_name=next(iter(names))
            if merged.nets[new_name]!=expected:
                extra=merged.nets[new_name]-expected
                raise MergeError(f'{source.alias}: source net {old_name!r} joined another net unexpectedly ({sorted(extra)[:5]}). Nothing was published.')
            source.net_map[old_name]=new_name
    if set(merged.components)!=expected_refs:
        raise MergeError('Combined netlist contains unexpected components; refusing to publish.')
    return {'components':len(expected_refs),'nets':len(merged.nets),'pins':len(merged.pins),'electrical_partitions':'exact match; sources isolated'}
