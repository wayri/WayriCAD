"""KiCad 10 schematic/project adapter; no pcbnew/SWIG dependency.

Native differential variants: instances/project/path/variant, KiCad 10 branch.
The 20260306 in_bom inversion fix is handled explicitly. No format upgrades.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
from typing import Any
import hashlib
import json
import os
import re
from .sexpr import Node, parse, properties

BASE = '<Default>'
FLAGS = {'dnp': False, 'in_bom': True, 'on_board': True,
         'in_pos_files': True, 'exclude_from_sim': False}
SAFE_VERSION = 20260306
VARIANT_TAGS = set(FLAGS) | {'name', 'field'}


def is_generated_field(name: str) -> bool:
    """KiCad 10 generated physical field: exactly one word-token ${NAME}.

    Such a field's stored value is locked to its name expression. Compound
    names are ordinary properties, not generated fields. See common/common.cpp
    IsGeneratedField and eeschema/sch_field.cpp SetName/SetText (KiCad 10).
    """
    return re.fullmatch(r'\$\{\w*\}', name) is not None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def natural(value: str):
    return tuple((1, int(x)) if x.isdigit() else (0, x.casefold())
                 for x in re.split(r'(\d+)', str(value)))


def normalized_path(value: str) -> str:
    return '/' + '/'.join(x for x in value.split('/') if x)


def read_flags(node: Node, differential: bool = False, version: int = SAFE_VERSION) -> dict:
    result = {} if differential else dict(FLAGS)
    for name in FLAGS:
        n = node.one(name)
        if n:
            value = n.val()
            if value not in ('yes','no'):
                raise ValueError(f'Unrecognized {name} boolean {value!r}.')
            result[name] = value == 'yes'
            if differential and name == 'in_bom' and version < 20260306:
                result[name] = not result[name]
    return result


def instance_node(node: Node, path: str, project_name: str | None = None) -> Node | None:
    instances = node.one('instances')
    found = []
    if instances:
        projects=instances.nodes('project')
        matching=[p for p in projects if p.val()==project_name] if project_name else []
        for project in matching or projects:
            for n in project.nodes('path'):
                if normalized_path(n.val()) == normalized_path(path):
                    found.append(n)
    if len(found) > 1:
        raise ValueError(f'Ambiguous instance path {path}. Open/save in KiCad first.')
    return found[0] if found else None


def variants(node: Node | None, version: int) -> tuple[dict, list[str]]:
    result, unknown = {}, []
    if node:
        for v in node.nodes('variant'):
            name = v.get('name')
            if not name or name.casefold() in {x.casefold() for x in result}:
                raise ValueError('Variant names must be nonempty and unique ignoring case.')
            unknown.extend(c.tag for c in v.children if c.tag not in VARIANT_TAGS)
            fields = {}
            for f in v.nodes('field'):
                unknown.extend('field/' + c.tag for c in f.children if c.tag not in ('name','value'))
                fields[f.get('name')] = f.get('value')
            result[name] = {'fields': fields, 'flags': read_flags(v, True, version)}
    return result, unknown


def variant_lookup(mapping: dict, name: str, default=None):
    return next((v for k, v in mapping.items() if k.casefold() == name.casefold()), default)

@dataclass
class Document:
    path: Path
    data: bytes
    text: str
    tree: Node
    version: int
    @classmethod
    def load(cls, path: Path):
        data = path.read_bytes()
        if len(data) > 128 * 1024 * 1024:
            raise ValueError(f'Schematic exceeds 128 MiB: {path.name}')
        text = data.decode('utf-8-sig')
        tree = parse(text)
        if tree.tag != 'kicad_sch':
            raise ValueError('Select a .kicad_sch or .kicad_pro file, not a board or library.')
        return cls(path, data, text, tree, int(tree.get('version','0')))

@dataclass
class Member:
    doc: Document
    symbol: Node
    instance: Node | None
    path: str
    unit: int
    uuid: str
    native: dict

@dataclass
class SheetContext:
    name: str
    path: str
    fields: dict
    flags: dict
    native: dict

@dataclass
class Component:
    id: str
    ref: str
    fields: dict
    flags: dict
    members: list[Member]
    ancestors: list[SheetContext]
    sheet: str
    lib_id: str
    native: dict
    problems: list[str] = field(default_factory=list)

class Project:
    def __init__(self, selected: str | Path):
        selected = Path(selected).expanduser().resolve(strict=True)
        self.pro_path = selected if selected.suffix == '.kicad_pro' else selected.with_suffix('.kicad_pro')
        self.root = selected.with_suffix('.kicad_sch') if selected.suffix in ('.kicad_pro','.kicad_pcb') else selected
        self.pro_data = self.pro_path.read_bytes() if self.pro_path.exists() else None
        self.pro = json.loads(self.pro_data.decode('utf-8-sig')) if self.pro_data else {}
        top_sheets=self.pro.get('schematic',{}).get('top_level_sheets',[])
        if selected.suffix=='.kicad_pro' and len(top_sheets)==1:
            filename=top_sheets[0].get('filename','')
            if filename:
                candidate=(self.pro_path.parent/filename.replace('\\','/')).resolve()
                if candidate.is_file():self.root=candidate
        if self.root.suffix != '.kicad_sch' or not self.root.is_file():
            raise ValueError('Choose the root .kicad_sch or its .kicad_pro file.')
        self.variables = self.pro.get('text_variables', {})
        if not isinstance(self.variables, dict) or any(not isinstance(v,str) for v in self.variables.values()):
            raise ValueError('Unsupported project text_variables format.')
        self.name = self.pro_path.stem
        self.documents: dict[Path,Document] = {}
        self.components: list[Component] = []
        self.sheet_records: list[tuple[Document,Node,Node|None,str]] = []
        self.blockers: list[str] = []
        self.warnings: list[str] = []
        self.variant_descriptions: dict[str,str] = {}
        self.native_presets = self.pro.get('schematic',{}).get('bom_presets',[])
        for item in self.pro.get('schematic',{}).get('variants',[]):
            self.variant_descriptions[item['name']] = item.get('description','')
        if len(top_sheets)>1:
            self.blockers.append('Flat/multiple top-level sheets require a dedicated adapter; this preview loads only the selected root. Production export and native writes are blocked.')
        if len(top_sheets)==1:
            listed=(self.pro_path.parent/top_sheets[0].get('filename','').replace('\\','/')).resolve()
            if listed!=self.root.resolve():
                self.blockers.append('Selected root does not match the project top-level sheet entry. Save/reopen the correct root in KiCad first.')
        root_doc = self._document(self.root)
        root_id = root_doc.tree.get('uuid')
        if not root_id:
            raise ValueError('Root sheet UUID missing. Open and save this project in KiCad 10.')
        self._walk(self.root, '/' + root_id, [], '/', ())
        self.hashes = {str(p):sha(d.data) for p,d in self.documents.items()}
        if self.pro_data is not None:
            self.hashes[str(self.pro_path)] = sha(self.pro_data)
        refs = defaultdict(list)
        for c in self.components:
            refs[c.ref].append(c)
        for ref, items in refs.items():
            if len(items) > 1:
                first=items[0];members=[m for c in items for m in c.members]
                def context(c):return [(a.flags,a.native) for a in c.ancestors]
                consistent=(len({m.unit for m in members})==len(members)
                    and all(c.lib_id==first.lib_id and c.fields==first.fields
                            and c.flags==first.flags and c.native==first.native
                            and context(c)==context(first) for c in items)
                    and '${SHEET' not in json.dumps([first.fields,first.native],ensure_ascii=False))
                if consistent:
                    first.members=members
                    for extra in items[1:]:self.components.remove(extra)
                    self.warnings.append(f'{ref}: consistent units across sheets are grouped as one physical component; sheet context uses the first unit.')
                else:self.blockers.append(f'Duplicate reference {ref} across sheets. Annotate or reconcile multi-unit fields before release.')
        self.components.sort(key=lambda c: natural(c.ref))
        self.by_id = {c.id: c for c in self.components}
        self.blockers = list(dict.fromkeys(self.blockers))
        self.warnings = list(dict.fromkeys(self.warnings))

    def _document(self, path: Path) -> Document:
        path = path.resolve(strict=True)
        if path not in self.documents:
            doc = self.documents[path] = Document.load(path)
            if doc.version > SAFE_VERSION:
                self.blockers.append(f'{path.name}: future file format {doc.version}; read-only inspection, no production export/writeback.')
            if doc.version < 20250922:
                self.warnings.append(f'{path.name}: pre-variant format. Save in KiCad 10 before native variant writeback.')
            if doc.tree.nodes('rule_area'):
                self.blockers.append(f'{path.name}: schematic rule areas need KiCad-native effective-attribute validation. This adapter will not guess their geometry-dependent DNP/BOM effects.')
        return self.documents[path]

    def _walk(self, path: Path, instance_path: str, ancestors: list[SheetContext], human: str, chain: tuple[Path,...]):
        path = path.resolve(strict=True)
        if path in chain or len(chain) > 64:
            raise ValueError('Circular or excessively deep sheet hierarchy.')
        doc = self._document(path)
        local: dict[str,Component] = {}
        for s in doc.tree.nodes('symbol'):
            if not s.one('lib_id'):
                continue
            props = {k:v[0] for k,v in properties(s).items()}
            inst = instance_node(s, instance_path, self.name)
            ref = inst.get('reference') if inst else props.get('Reference','')
            if ref.startswith('#'):
                continue
            if not ref:
                raise ValueError(f'Missing reference in {path.name}.')
            if not inst:
                self.blockers.append(f'{ref}: missing instance path. Save/annotate in KiCad 10 before release.')
            if '?' in ref:
                self.blockers.append(f'{ref}: unannotated symbol.')
            native, unknown = variants(inst, doc.version)
            for name in native:
                if name.casefold() not in {n.casefold() for n in self.variant_descriptions}:
                    self.variant_descriptions[name] = ''
            if unknown:
                self.blockers.append(f'{ref}: unknown variant tokens {", ".join(unknown)}; release/write blocked.')
            props['Reference'] = ref
            uid = s.get('uuid')
            if not uid:
                raise ValueError(f'{ref}: missing UUID.')
            member = Member(doc,s,inst,instance_path,int(inst.get('unit','1') if inst else s.get('unit','1')),uid,native)
            flags = read_flags(s)
            if ref in local:
                c = local[ref]
                if any(m.unit == member.unit for m in c.members) or c.lib_id != s.get('lib_id'):
                    self.blockers.append(f'{ref}: duplicate unit/reference, cannot safely count physical parts.')
                if c.fields != props or c.flags != flags or c.native != native:
                    c.problems.append('Multi-unit fields or variant data disagree; reconcile in KiCad.')
                    self.blockers.append(f'{ref}: conflicting multi-unit data.')
                c.members.append(member)
                c.id = instance_path + '/' + min(m.uuid for m in c.members)
            else:
                c = Component(instance_path+'/'+uid,ref,props,flags,[member],ancestors,human,s.get('lib_id'),native)
                local[ref] = c
        self.components.extend(local.values())
        for s in doc.tree.nodes('sheet'):
            props = {k:v[0] for k,v in properties(s).items()}
            file = props.get('Sheetfile',props.get('Sheet file',''))
            name = props.get('Sheetname',props.get('Sheet name',''))
            if not file or file.startswith('kicad-embed:'):
                raise ValueError('Missing/embedded hierarchical sheet file. Extract the sheet to a local file in KiCad first.')
            env = {**os.environ, **self.variables, 'KIPRJMOD':str(self.root.parent)}
            file = re.sub(r'\$\{([^}]+)\}', lambda m: env.get(m[1],m[0]), file)
            if '${' in file:
                raise ValueError(f'Unresolved sheet filename variable: {file}')
            file = file.replace('\\','/')
            child = (path.parent / file).resolve()
            if not child.is_file():
                raise ValueError(f'Missing child sheet {name}: {child}')
            inst = instance_node(s, instance_path, self.name)
            native, unknown = variants(inst,doc.version)
            if unknown:
                self.blockers.append(f'Sheet {name}: unknown variant attributes.')
            for v in native:
                if v.casefold() not in {n.casefold() for n in self.variant_descriptions}:
                    self.variant_descriptions[v] = ''
            context = SheetContext(name,instance_path,props,read_flags(s),native)
            self.sheet_records.append((doc,s,inst,instance_path))
            self._walk(child,instance_path+'/'+s.get('uuid'),ancestors+[context],human+name+'/',chain+(path,))

    def check_unchanged(self):
        for p, expected in self.hashes.items():
            path = Path(p)
            if not path.exists() or sha(path.read_bytes()) != expected:
                raise ValueError(f'Source changed since opening: {path.name}. Reopen the project and review conflicts.')
        if self.pro_data is None and self.pro_path.exists():
            raise ValueError('A project file was created since opening. Reopen before writing.')

    def status(self) -> dict[str,Any]:
        return {'name': self.name, 'path': str(self.root), 'files': len(self.documents),
                'components': len(self.components), 'versions': sorted({d.version for d in self.documents.values()}),
                'blockers': self.blockers, 'warnings': self.warnings,
                'native_presets': self.native_presets,
                'native_write_supported': not self.blockers and all(d.version == SAFE_VERSION for d in self.documents.values())}
