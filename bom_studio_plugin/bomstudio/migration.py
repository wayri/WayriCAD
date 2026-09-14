"""Native KiCad format upgrade on a checked, independently published project copy.

KiCad's single-file upgrade command does not migrate legacy root instance tables.
Preserve their exact UUID/reference/unit/page mappings across the native resave;
never infer annotation from a symbol's display field. Native XML connectivity
before and after is the acceptance check, in addition to hierarchy UUID checks.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from .sexpr import parse, properties, apply_edits, quote

FORMAT = 20260306
IGNORE = {'.git', '__pycache__', '.venv', 'node_modules', '.wayricad-upgrade'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run(command, timeout=45):
    result = subprocess.run([str(x) for x in command], capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=timeout,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise ValueError('KiCad could not validate the project copy: ' +
                         (result.stderr or result.stdout)[-3000:])
    return result.stdout


def executable(path=None):
    value = path or os.environ.get('KICAD_CLI') or shutil.which('kicad-cli')
    if not value and os.name == 'nt':
        candidates = sorted(Path(os.environ.get('PROGRAMFILES','C:/Program Files'),
                                  'KiCad').glob('10.*/bin/kicad-cli.exe'), reverse=True)
        value = str(candidates[0]) if candidates else None
    if not value:
        raise ValueError('Install KiCad 10 or provide the kicad-cli executable path.')
    version = _run([value, 'version']).strip()
    if not re.match(r'^10\.', version):
        raise ValueError('This migration adapter is validated for KiCad 10; found ' + version)
    return str(value), version


def _hierarchy(root):
    """Return each physical screen and each visited instance path, without writes."""
    root = Path(root).resolve(strict=True)
    project = root.with_suffix('.kicad_pro')
    variables = json.loads(project.read_text(encoding='utf-8-sig')).get('text_variables', {}) if project.exists() else {}
    documents = {}; visits = []
    def walk(path, relative, chain):
        path = path.resolve(strict=True)
        if not path.is_relative_to(root.parent):
            raise ValueError('A child sheet is outside this project directory. Localize the hierarchy before upgrading a copy: ' + str(path))
        if path in chain or len(chain) > 64:
            raise ValueError('Circular or excessively deep schematic hierarchy.')
        if path not in documents:
            text = path.read_text(encoding='utf-8-sig');tree = parse(text)
            if tree.tag != 'kicad_sch' or int(tree.get('version','0')) > FORMAT:
                raise ValueError('Unsupported or future schematic format: ' + path.name)
            documents[path] = (text,tree)
        text,tree = documents[path];visits.append((path,relative))
        for sheet in tree.nodes('sheet'):
            props = properties(sheet)
            filename = props.get('Sheetfile',props.get('Sheet file',('',)))[0]
            filename = re.sub(r'\$\{([^}]+)\}',lambda m:str(variables.get(m[1],m[0])),filename)
            if not filename or '${' in filename or Path(filename).is_absolute() or filename.startswith('kicad-embed:'):
                raise ValueError('Child sheet paths must be project-relative before migrating: ' + filename)
            uid = sheet.get('uuid')
            if not uid:raise ValueError('Child sheet UUID is missing.')
            walk(path.parent / filename.replace('\\','/'),relative+'/'+uid,chain+(path,))
    walk(root,'',())
    return documents,visits


def _legacy_records(root,documents,visits):
    root = Path(root).resolve(strict=True)
    root_tree = documents[root][1];root_id=root_tree.get('uuid')
    if not root_id:raise ValueError('Root schematic UUID is missing.')
    tables = {}
    for kind in ('symbol_instances','sheet_instances'):
        table=root_tree.one(kind);rows={}
        for entry in table.nodes('path') if table else []:
            path=entry.val().rstrip('/')
            if path in rows:raise ValueError('Ambiguous legacy instance path: '+path)
            rows[path]=entry
        tables[kind]=rows
    records=defaultdict(list)
    if not tables['symbol_instances']:
        return records
    used=set()
    for path,relative in visits:
        tree=documents[path][1]
        library=tree.one('lib_symbols')
        definitions={n.val():n for n in library.nodes('symbol')} if library else {}
        for symbol in tree.nodes('symbol'):
            if not symbol.one('lib_id'):continue
            uid=symbol.get('uuid');key=relative+'/'+uid
            old=tables['symbol_instances'].get(key)
            if old is None:raise ValueError('Legacy annotation is incomplete for '+path.name+' '+key)
            ref=old.get('reference');unit=old.get('unit')
            if not ref or '?' in ref or not unit or not unit.isdigit():
                raise ValueError('Legacy annotation requires correction: '+key)
            power_name=''
            definition=definitions.get(symbol.get('lib_id'))
            # KiCad 6/7 power symbols name nets by their invisible power-input
            # pin. KiCad 8+ uses Value instead (KiCad 8 release documentation).
            # Preserve electrical meaning even if an old display Value differed.
            if int(tree.get('version','0')) in (20211123,20230121) and definition and definition.one('power'):
                names={pin.get('name') for unit_node in definition.nodes('symbol')
                       for pin in unit_node.nodes('pin')
                       if pin.val()=='power_in' and any(a.value=='hide' for a in pin.atoms)}
                if len(names)==1:power_name=next(iter(names))
                elif names:raise ValueError('Ambiguous legacy power net definition: '+symbol.get('lib_id'))
            records[(path,uid,'symbol')].append((root_id+relative,ref,unit,old.get('value'),old.get('footprint'),power_name));used.add(key)
        for sheet in tree.nodes('sheet'):
            uid=sheet.get('uuid');old=tables['sheet_instances'].get(relative+'/'+uid)
            if old is None or not old.get('page'):
                raise ValueError('Legacy sheet page mapping is missing: '+relative+'/'+uid)
            records[(path,uid,'sheet')].append((root_id+relative,old.get('page'),''))
    if used != set(tables['symbol_instances']):
        raise ValueError('Legacy annotation contains unreachable symbols; repair the hierarchy before migration.')
    return records


def _restore_instances(stage,source,records,project_name):
    source = Path(source).resolve(strict=True)
    files=defaultdict(list)
    for (path,uid,kind),rows in records.items():files[path].append((uid,kind,rows))
    for path,items in files.items():
        target=stage/path.relative_to(source);text=target.read_text(encoding='utf-8-sig');tree=parse(text);edits=[]
        for uid,kind,rows in items:
            nodes=[n for n in tree.nodes(kind) if n.get('uuid')==uid]
            if len(nodes)!=1:raise ValueError('KiCad changed or duplicated a placement UUID during migration: '+uid)
            node=nodes[0]
            if node.one('instances'):
                raise ValueError('Mixed legacy/modern instance records require explicit reconciliation before migration.')
            paths=[]
            for row in rows:
                path_id,reference,unit=row[:3]
                attributes='(reference '+quote(reference)+') (unit '+unit+')' if kind=='symbol' else '(page '+quote(reference)+')'
                paths.append('(path '+quote('/'+path_id)+' '+attributes+')')
            value='\n (instances (project '+quote(project_name)+' '+' '.join(paths)+'))\n'
            edits.append((node.end-1,node.end-1,value))
        target.write_text(apply_edits(text,edits),encoding='utf-8',newline='\n')


def _restore_effective_fields(stage,source,records,native_circuit):
    """Retain KiCad's pre-upgrade effective fields, including power net values.

    Old root instance caches may override physical screen properties. Multi-unit
    screens may also contain stale secondary-unit fields. Native export is the
    authority for the original effective component, not an arbitrary first unit.
    """
    source = Path(source).resolve(strict=True)
    canonical={ref:dict(fields,Value=value,Footprint=footprint)
               for ref,value,footprint,fields in native_circuit['components']}
    files=defaultdict(list)
    for (path,uid,kind),rows in records.items():
        if kind!='symbol':continue
        desired=[]
        for row in rows:
            fields=dict(canonical.get(row[1],{'Value':row[3],'Footprint':row[4]}))
            if len(row)>5 and row[5]:fields['Value']=row[5]
            desired.append(fields)
        if any(d!=desired[0] for d in desired[1:]):
            raise ValueError('Shared sheet instance fields differ; split the sheet in KiCad before migration: '+uid)
        files[path].append((uid,desired[0]))
    changed=0
    for path,items in files.items():
        target=stage/path.relative_to(source);text=target.read_text(encoding='utf-8-sig');tree=parse(text);edits=[]
        for uid,desired in items:
            nodes=[n for n in tree.nodes('symbol') if n.get('uuid')==uid]
            if len(nodes)!=1:raise ValueError('Placement UUID changed while restoring native fields: '+uid)
            node=nodes[0];props=properties(node)
            for name,value in desired.items():
                if name=='Reference':continue
                if name in props:
                    old,_,atom=props[name]
                    # Native XML expands expressions. Preserve editable source
                    # expressions rather than baking today's variable values;
                    # the final native comparison rejects a real discrepancy.
                    if '${' in old:continue
                    if old!=value:edits.append((atom.start,atom.end,quote(value)));changed+=1
                elif value:
                    edits.append((node.end-1,node.end-1,'\n (property '+quote(name)+' '+quote(value)+' (at 0 0 0) (hide yes))\n'));changed+=1
        if edits:target.write_text(apply_edits(text,edits),encoding='utf-8',newline='\n')
    return changed


def _netlist(cli,root,target):
    _run([cli,'sch','export','netlist','--format','kicadxml','--output',target,root])
    tree=ET.parse(target).getroot()
    components=[]
    for item in tree.findall('./components/comp'):
        fields=tuple(sorted((f.attrib.get('name',''),f.text or '') for f in item.findall('./fields/field')))
        components.append((item.attrib['ref'],item.findtext('value',''),item.findtext('footprint',''),fields))
    nets=[]
    for net in tree.findall('./nets/net'):
        pins=tuple(sorted((n.attrib.get('ref',''),n.attrib.get('pin','')) for n in net.findall('node')))
        nets.append((net.attrib.get('name',''),pins))
    return {'components':sorted(components),'nets':sorted(nets)}


def upgrade_copy(selected,destination,*,cli=None,validator=None,progress=None):
    root=Path(selected).expanduser().resolve(strict=True)
    if root.suffix=='.kicad_pro':root=root.with_suffix('.kicad_sch')
    if root.suffix!='.kicad_sch':raise ValueError('Select a root schematic or its project file.')
    source=root.parent;destination=Path(destination).expanduser().resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Choose a new destination directory outside the source project.')
    documents,visits=_hierarchy(root);records=_legacy_records(root,documents,visits)
    command,version=executable(cli)
    files=[];total=0
    for directory,dirs,names in os.walk(source,followlinks=False):
        dirs[:]=[n for n in dirs if n not in IGNORE and not n.endswith('-backups')]
        for name in dirs+names:
            if (Path(directory)/name).is_symlink():raise ValueError('Project symlinks must be localized before copying.')
        for name in names:
            path=Path(directory)/name
            if name.endswith(('.lck','.lock','.kicad_prl')):continue
            total+=path.stat().st_size;files.append(path)
    if len(files)>20000 or total>1024**3:raise ValueError('Project copy exceeds 20,000 files or 1 GiB.')
    hashes={p.relative_to(source).as_posix():_sha(p) for p in files}
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.wayricad-upgrade-',dir=destination.parent) as temporary:
        temporary=Path(temporary);stage=temporary/'project';stage.mkdir()
        for path in files:
            target=stage/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        staged_root=stage/root.name
        before=_netlist(command,staged_root,temporary/'before.xml')
        for index,(path,(_,tree)) in enumerate(documents.items()):
            if progress:progress(index,len(documents),path.name)
            if int(tree.get('version','0'))!=FORMAT:
                _run([command,'sch','upgrade','--force',stage/path.relative_to(source)])
        _restore_instances(stage,source,records,root.stem)
        reconciled=_restore_effective_fields(stage,source,records,before)
        after=_netlist(command,staged_root,temporary/'after.xml')
        if before!=after:raise ValueError('Native connectivity, annotation or component fields changed during upgrade; source is untouched and no copy was published.')
        updated,_=_hierarchy(staged_root)
        if len(updated)!=len(documents) or any(int(tree.get('version','0'))!=FORMAT for _,tree in updated.values()):
            raise ValueError('The complete hierarchy was not upgraded to the supported format.')
        validation=validator(staged_root) if validator else {}
        for relative,expected in hashes.items():
            if _sha(source/relative)!=expected:raise ValueError('Source changed during migration: '+relative)
        report={'schema':1,'source':str(root),'destination':str(destination/root.name),
                'kicad_version':version,'schematics':len(documents),
                'legacy_instance_placements':sum(len(v) for v in records.values()),
                'native_effective_field_reconciliations':reconciled,
                'native_components':len(after['components']),'native_nets':len(after['nets']),
                'source_hashes':hashes,'connectivity_preserved':True,'validation':validation}
        (stage/'wayricad-upgrade.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        if destination.exists():raise ValueError('Destination appeared during migration; choose a new directory.')
        os.rename(stage,destination)
    return report
