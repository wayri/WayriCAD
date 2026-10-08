#!/usr/bin/env python3
"""KiCad 10 Design Variant Manager.

Standard-library native variant parser and loss-preserving serializer.
It performs a loss-minimizing rewrite of KiCad .kicad_sch S-expressions:
  * snapshots the effective state of every named variant,
  * promotes one selected named variant to the base/default state,
  * rebases every other variant so its effective state is unchanged,
  * optionally removes or keeps the promoted named variant,
  * updates schematic variant metadata in the matching .kicad_pro,
  * writes timestamped backups and uses atomic replacement.

This is deliberately conservative. Unsupported or ambiguous cases are rejected
rather than guessed at.
"""
from __future__ import annotations

import argparse
import csv
import copy
import dataclasses
import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

APP_NAME = "WayriCAD Variant Manager"
APP_VERSION = "0.6.1"
BOM_LOGIC_FIX_VERSION = 20260306
SUPPORTED_MIN_VARIANT_VERSION = 20250922


class VariantPromoterError(RuntimeError):
    pass


@dataclasses.dataclass
class Token:
    kind: str  # atom | string
    value: str
    start: int
    end: int


@dataclasses.dataclass
class Node:
    start: int
    end: int
    items: List[Union["Node", Token]]

    @property
    def head_token(self) -> Optional[Token]:
        if self.items and isinstance(self.items[0], Token):
            return self.items[0]
        return None

    @property
    def head(self) -> str:
        t = self.head_token
        return t.value if t else ""

    def child_nodes(self, head: Optional[str] = None) -> List["Node"]:
        out = [x for x in self.items[1:] if isinstance(x, Node)]
        if head is not None:
            out = [x for x in out if x.head == head]
        return out

    def child_node(self, head: str) -> Optional["Node"]:
        xs = self.child_nodes(head)
        return xs[0] if xs else None

    def scalar_tokens(self) -> List[Token]:
        return [x for x in self.items[1:] if isinstance(x, Token)]

    def scalar(self, index: int = 0, default: Optional[str] = None) -> Optional[str]:
        vals = self.scalar_tokens()
        return vals[index].value if index < len(vals) else default

    def scalar_token(self, index: int = 0) -> Optional[Token]:
        vals = self.scalar_tokens()
        return vals[index] if index < len(vals) else None


class SExprParser:
    """Small loss-aware S-expression parser retaining character spans."""

    def __init__(self, text: str):
        self.text = text
        self.tokens: List[Token] = []
        self._tokenize()
        self.i = 0

    def _tokenize(self) -> None:
        s = self.text
        n = len(s)
        i = 0
        toks: List[Token] = []
        while i < n:
            c = s[i]
            if c.isspace():
                i += 1
                continue
            if c == ';':
                # Rare in KiCad-generated files, but preserve by ignoring to EOL.
                j = s.find('\n', i)
                i = n if j < 0 else j + 1
                continue
            if c == '(' or c == ')':
                toks.append(Token('lparen' if c == '(' else 'rparen', c, i, i + 1))
                i += 1
                continue
            if c == '"':
                start = i
                i += 1
                buf: List[str] = []
                while i < n:
                    c = s[i]
                    if c == '"':
                        i += 1
                        toks.append(Token('string', ''.join(buf), start, i))
                        break
                    if c == '\\':
                        i += 1
                        if i >= n:
                            raise VariantPromoterError("Unterminated escape in quoted string")
                        esc = s[i]
                        mapping = {'n': '\n', 'r': '\r', 't': '\t', '"': '"', '\\': '\\'}
                        buf.append(mapping.get(esc, "\\" + esc))
                        i += 1
                    else:
                        buf.append(c)
                        i += 1
                else:
                    raise VariantPromoterError("Unterminated quoted string")
                continue
            start = i
            while i < n and (not s[i].isspace()) and s[i] not in '()':
                i += 1
            toks.append(Token('atom', s[start:i], start, i))
        self.tokens = toks

    def parse(self) -> Node:
        if not self.tokens:
            raise VariantPromoterError("Empty schematic file")
        node = self._parse_node()
        if self.i != len(self.tokens):
            raise VariantPromoterError("Unexpected extra tokens after root S-expression")
        return node

    def _parse_node(self) -> Node:
        if self.i >= len(self.tokens) or self.tokens[self.i].kind != 'lparen':
            raise VariantPromoterError("Expected '('")
        start = self.tokens[self.i].start
        self.i += 1
        items: List[Union[Node, Token]] = []
        while self.i < len(self.tokens):
            tok = self.tokens[self.i]
            if tok.kind == 'rparen':
                self.i += 1
                return Node(start, tok.end, items)
            if tok.kind == 'lparen':
                items.append(self._parse_node())
            else:
                items.append(tok)
                self.i += 1
        raise VariantPromoterError("Unclosed S-expression")


@dataclasses.dataclass
class State:
    dnp: bool = False
    exclude_from_sim: bool = False
    excluded_from_bom: bool = False
    excluded_from_board: bool = False
    excluded_from_pos: bool = False
    fields: Dict[str, str] = dataclasses.field(default_factory=dict)

    def clone(self) -> "State":
        return State(
            self.dnp,
            self.exclude_from_sim,
            self.excluded_from_bom,
            self.excluded_from_board,
            self.excluded_from_pos,
            dict(self.fields),
        )

    def signature(self) -> Tuple:
        return (
            self.dnp,
            self.exclude_from_sim,
            self.excluded_from_bom,
            self.excluded_from_board,
            self.excluded_from_pos,
            tuple(sorted(self.fields.items())),
        )


@dataclasses.dataclass
class InstanceInfo:
    path_node: Node
    project_name: str
    path_id: str
    reference: str
    variants: Dict[str, Node]


@dataclasses.dataclass
class ObjectInfo:
    kind: str  # symbol | sheet
    node: Node
    uuid: str
    label: str
    base: State
    property_nodes: Dict[str, Node]
    instances: List[InstanceInfo]


@dataclasses.dataclass
class ParsedSch:
    path: Path
    text: str
    root: Node
    version: int
    objects: List[ObjectInfo]
    variant_names: set[str]
    child_sheet_files: List[str]
    sha256: str


@dataclasses.dataclass
class Edit:
    start: int
    end: int
    replacement: str
    why: str


@dataclasses.dataclass
class PlannedFile:
    path: Path
    old_sha256: str
    new_text: str
    edits: List[Edit]


@dataclasses.dataclass
class PromotionPlan:
    source_root: Path
    project_file: Optional[Path]
    selected_variant: str
    keep_source: bool
    schematic_files: List[PlannedFile]
    project_old_sha256: Optional[str]
    project_new_text: Optional[str]
    variants_before: List[str]
    variants_after: List[str]
    summary: List[str]


# ---------- S-expression helpers ----------

def _parse_bool(v: Optional[str], what: str) -> bool:
    if v == 'yes':
        return True
    if v == 'no':
        return False
    raise VariantPromoterError(f"Expected yes/no for {what}, got {v!r}")


def _q(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def _eol(text: str) -> str:
    """Return the file's dominant line ending without normalizing it."""
    crlf = text.count('\r\n')
    lf = text.count('\n') - crlf
    return '\r\n' if crlf > lf else '\n'


def _line_indent(text: str, pos: int) -> str:
    line_start = text.rfind('\n', 0, pos) + 1
    m = re.match(r'[ \t]*', text[line_start:pos])
    return m.group(0) if m else ''


def _child_indent(text: str, parent: Node) -> str:
    children = parent.child_nodes()
    if children:
        return _line_indent(text, children[0].start)
    return _line_indent(text, parent.start) + '  '


def _closing_line_start(text: str, node: Node) -> int:
    close = node.end - 1
    ls = text.rfind('\n', node.start, close) + 1
    if text[ls:close].strip() == '':
        return ls
    return close


def _property_parts(p: Node) -> Tuple[Optional[str], Optional[str], Optional[Token]]:
    vals = p.scalar_tokens()
    offset = 1 if vals and vals[0].value == 'private' else 0
    if len(vals) < offset + 2:
        return None, None, None
    return vals[offset].value, vals[offset + 1].value, vals[offset + 1]


def _property_map(node: Node) -> Dict[str, Node]:
    out: Dict[str, Node] = {}
    for p in node.child_nodes('property'):
        name, value, _ = _property_parts(p)
        if name is not None and value is not None:
            if name in out:
                raise VariantPromoterError(f"Duplicate property {name!r} in one schematic object")
            out[name] = p
    return out


def _uuid(node: Node) -> str:
    u = node.child_node('uuid')
    return (u.scalar(0) if u else None) or '<no-uuid>'


def _base_state(node: Node, kind: str) -> Tuple[State, Dict[str, Node]]:
    props = _property_map(node)
    st = State(fields={name: (_property_parts(p)[1] or '') for name, p in props.items()})
    n = node.child_node('dnp')
    if n:
        st.dnp = _parse_bool(n.scalar(0), 'dnp')
    n = node.child_node('exclude_from_sim')
    if n:
        st.exclude_from_sim = _parse_bool(n.scalar(0), 'exclude_from_sim')
    n = node.child_node('in_bom')
    if n:
        st.excluded_from_bom = not _parse_bool(n.scalar(0), 'in_bom')
    n = node.child_node('on_board')
    if n:
        st.excluded_from_board = not _parse_bool(n.scalar(0), 'on_board')
    n = node.child_node('in_pos_files')
    if n:
        if kind == 'sheet':
            raise VariantPromoterError("Found unsupported sheet-level base in_pos_files token")
        st.excluded_from_pos = not _parse_bool(n.scalar(0), 'in_pos_files')
    return st, props


def _variant_name(vnode: Node) -> str:
    n = vnode.child_node('name')
    if not n or n.scalar(0) is None:
        raise VariantPromoterError("Variant block without a name")
    return n.scalar(0) or ''


def _effective_state(base: State, vnode: Optional[Node], version: int) -> State:
    st = base.clone()
    if vnode is None:
        return st
    allowed = {'name', 'dnp', 'exclude_from_sim', 'in_bom', 'on_board', 'in_pos_files', 'field'}
    for c in vnode.child_nodes():
        if c.head not in allowed:
            raise VariantPromoterError(f"Unsupported variant token {c.head!r}; refusing to guess")
        if c.head == 'name':
            continue
        if c.head == 'dnp':
            st.dnp = _parse_bool(c.scalar(0), 'variant dnp')
        elif c.head == 'exclude_from_sim':
            st.exclude_from_sim = _parse_bool(c.scalar(0), 'variant exclude_from_sim')
        elif c.head == 'in_bom':
            raw = _parse_bool(c.scalar(0), 'variant in_bom')
            st.excluded_from_bom = (not raw) if version >= BOM_LOGIC_FIX_VERSION else raw
        elif c.head == 'on_board':
            st.excluded_from_board = not _parse_bool(c.scalar(0), 'variant on_board')
        elif c.head == 'in_pos_files':
            st.excluded_from_pos = not _parse_bool(c.scalar(0), 'variant in_pos_files')
        elif c.head == 'field':
            if any(child.head not in {'name', 'value'} for child in c.child_nodes()):
                raise VariantPromoterError('Unsupported variant field token; refusing to discard unknown data')
            name_node = c.child_node('name')
            value_node = c.child_node('value')
            if not name_node or not value_node:
                raise VariantPromoterError("Variant field must contain name and value")
            name = name_node.scalar(0)
            value = value_node.scalar(0)
            if name is None or value is None:
                raise VariantPromoterError("Variant field has missing name/value")
            st.fields[name] = value
    return st


def _parse_instances(node: Node) -> List[InstanceInfo]:
    out: List[InstanceInfo] = []
    insts = node.child_node('instances')
    if not insts:
        return out
    for project in insts.child_nodes('project'):
        project_name = project.scalar(0, '') or ''
        for path in project.child_nodes('path'):
            path_id = path.scalar(0, '') or ''
            refn = path.child_node('reference')
            reference = (refn.scalar(0) if refn else '') or ''
            variants: Dict[str, Node] = {}
            for v in path.child_nodes('variant'):
                name = _variant_name(v)
                if name in variants:
                    raise VariantPromoterError(f"Duplicate variant {name!r} on instance {path_id}")
                variants[name] = v
            out.append(InstanceInfo(path, project_name, path_id, reference, variants))
    return out


def parse_schematic(path: Path) -> ParsedSch:
    try:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode('utf-8')
    except UnicodeDecodeError as e:
        raise VariantPromoterError(f"{path}: not UTF-8: {e}") from e
    root = SExprParser(text).parse()
    if root.head != 'kicad_sch':
        raise VariantPromoterError(f"{path}: root is not (kicad_sch ...)")
    ver_node = root.child_node('version')
    if not ver_node or not (ver_node.scalar(0) or '').isdigit():
        raise VariantPromoterError(f"{path}: cannot read KiCad schematic file version")
    version = int(ver_node.scalar(0) or '0')
    objects: List[ObjectInfo] = []
    names: set[str] = set()
    child_files: List[str] = []

    for kind in ('symbol', 'sheet'):
        for node in root.child_nodes(kind):
            base, props = _base_state(node, kind)
            instances = _parse_instances(node)
            if kind == 'sheet':
                for inst in instances:
                    for vname, vnode in inst.variants.items():
                        unsupported = [c.head for c in vnode.child_nodes() if c.head in ('on_board', 'in_pos_files')]
                        if unsupported:
                            raise VariantPromoterError(
                                f"{path.name}: sheet {_uuid(node)} variant {vname!r} contains "
                                f"{', '.join(unsupported)}, which KiCad 10's schematic writer does not "
                                "round-trip for named sheet variants. Refusing to rewrite this file."
                            )
            for inst in instances:
                names.update(inst.variants.keys())
            uid = _uuid(node)
            if kind == 'symbol':
                label = base.fields.get('Reference', uid)
            else:
                label = base.fields.get('Sheetname', base.fields.get('Sheet name', uid))
                sf = base.fields.get('Sheetfile') or base.fields.get('Sheet file')
                if sf:
                    child_files.append(sf)
            objects.append(ObjectInfo(kind, node, uid, label, base, props, instances))

    return ParsedSch(
        path=path,
        text=text,
        root=root,
        version=version,
        objects=objects,
        variant_names=names,
        child_sheet_files=child_files,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


# ---------- project metadata / hierarchy ----------

def find_project_file(root_sch: Path) -> Optional[Path]:
    """Find the owning project for a selected schematic.

    Normal KiCad projects use the same stem. Flat multi-root projects can have
    top-level schematic filenames that differ from the .kicad_pro stem, so if
    there is no exact match we scan sibling projects for an explicit
    schematic.top_level_sheets reference.
    """
    root_sch = root_sch.resolve()
    exact = root_sch.with_suffix('.kicad_pro')
    if exact.exists():
        return exact

    matches: List[Path] = []
    for candidate in root_sch.parent.glob('*.kicad_pro'):
        try:
            data = json.loads(candidate.read_text(encoding='utf-8'))
            schematic = data.get('schematic', {})
            entries = schematic.get('top_level_sheets', []) if isinstance(schematic, dict) else []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get('filename'), str):
                    continue
                try:
                    referenced = _resolve_sheet_path(candidate.parent, entry['filename'])
                except VariantPromoterError:
                    continue
                if referenced == root_sch:
                    matches.append(candidate.resolve())
                    break
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    matches = sorted(set(matches))
    if len(matches) > 1:
        raise VariantPromoterError(
            f"{root_sch.name} is referenced as a top-level sheet by multiple .kicad_pro files: "
            + ', '.join(p.name for p in matches)
        )
    return matches[0] if matches else None


def load_project_variants(project_file: Optional[Path]) -> Tuple[List[str], Dict[str, dict], Optional[dict], Optional[str]]:
    if not project_file or not project_file.exists():
        return [], {}, None, None
    raw_bytes = project_file.read_bytes()
    try:
        raw = raw_bytes.decode('utf-8')
    except UnicodeDecodeError as e:
        raise VariantPromoterError(f"{project_file.name}: not UTF-8: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise VariantPromoterError(f"Cannot parse {project_file.name}: {e}") from e
    schematic = data.get('schematic', {})
    if schematic is None:
        schematic = {}
    if not isinstance(schematic, dict):
        raise VariantPromoterError("project schematic section is not an object")
    variants = schematic.get('variants', [])
    names: List[str] = []
    entries: Dict[str, dict] = {}
    if variants is not None:
        if not isinstance(variants, list):
            raise VariantPromoterError("project schematic.variants is not an array")
        for entry in variants:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
                raise VariantPromoterError("Malformed project variant metadata; refusing to discard it")
            name = entry['name']
            if not name.strip() or name in entries:
                raise VariantPromoterError("Empty or duplicate project variant name")
            names.append(name)
            entries[name] = copy.deepcopy(entry)
    return names, entries, data, hashlib.sha256(raw_bytes).hexdigest()


def project_top_level_sheets(project_file: Optional[Path], project_data: Optional[dict]) -> List[Path]:
    """Return KiCad 10 flat-hierarchy top-level schematic files from .kicad_pro."""
    if not project_file or not project_data:
        return []
    schematic = project_data.get('schematic', {})
    if not isinstance(schematic, dict):
        return []
    entries = schematic.get('top_level_sheets', []) or []
    if not isinstance(entries, list):
        raise VariantPromoterError("project schematic.top_level_sheets is not an array")
    out: List[Path] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise VariantPromoterError("project schematic.top_level_sheets contains a non-object entry")
        filename = entry.get('filename')
        if not isinstance(filename, str) or not filename.strip():
            raise VariantPromoterError("project schematic.top_level_sheets entry is missing filename")
        out.append(_resolve_sheet_path(project_file.parent, filename))
    return out


def _resolve_sheet_path(base_dir: Path, raw: str) -> Path:
    s = raw.replace('${KIPRJMOD}', str(base_dir))
    unresolved: List[str] = []
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in os.environ:
            return os.environ[key]
        unresolved.append(key)
        return m.group(0)
    s = re.sub(r'\$\{([^}]+)\}', repl, s)
    if unresolved:
        raise VariantPromoterError(
            f"Cannot resolve sheet path {raw!r}; missing environment variable(s): {', '.join(unresolved)}"
        )
    p = Path(s)
    if not p.is_absolute():
        p = base_dir / p
    for ancestor in (p, *p.parents):
        if ancestor.is_symlink():
            raise VariantPromoterError(f"Symlinked hierarchy paths are not supported: {ancestor}")
    return p.resolve()


def discover_hierarchy(
    root_sch: Path,
    project_file: Optional[Path] = None,
    project_data: Optional[dict] = None,
) -> List[ParsedSch]:
    root_sch = root_sch.resolve()
    queue = [root_sch]
    # KiCad 10 can use a flat hierarchy with several project-level root sheets.
    # Include them all before following ordinary child-sheet references.
    for top in project_top_level_sheets(project_file, project_data):
        if top not in queue:
            queue.append(top)
    parsed: Dict[Path, ParsedSch] = {}
    while queue:
        p = queue.pop(0)
        if p in parsed:
            continue
        if not p.exists():
            raise VariantPromoterError(f"Referenced schematic does not exist: {p}")
        sch = parse_schematic(p)
        parsed[p] = sch
        for raw in sch.child_sheet_files:
            child = _resolve_sheet_path(p.parent, raw.replace('${KIPRJMOD}', str(project_file.parent if project_file else root_sch.parent)))
            if child not in parsed:
                queue.append(child)
    return list(parsed.values())


# ---------- transformation ----------

_FLAG_SPEC = [
    ('dnp', 'dnp', False, lambda st: st.dnp, lambda x, ver: 'yes' if x else 'no'),
    ('exclude_from_sim', 'exclude_from_sim', False, lambda st: st.exclude_from_sim, lambda x, ver: 'yes' if x else 'no'),
    ('in_bom', 'excluded_from_bom', False, lambda st: st.excluded_from_bom, lambda x, ver: 'no' if x else 'yes'),
    ('on_board', 'excluded_from_board', False, lambda st: st.excluded_from_board, lambda x, ver: 'no' if x else 'yes'),
    ('in_pos_files', 'excluded_from_pos', False, lambda st: st.excluded_from_pos, lambda x, ver: 'no' if x else 'yes'),
]


def _variant_flag_text(tag: str, value_internal: bool, version: int) -> str:
    if tag == 'dnp' or tag == 'exclude_from_sim':
        raw = value_internal
    elif tag == 'in_bom':
        raw = (not value_internal) if version >= BOM_LOGIC_FIX_VERSION else value_internal
    elif tag == 'on_board' or tag == 'in_pos_files':
        raw = not value_internal
    else:
        raise AssertionError(tag)
    return 'yes' if raw else 'no'


def _state_diff(base: State, desired: State, kind: str) -> Tuple[List[Tuple[str, bool]], Dict[str, str]]:
    flags: List[Tuple[str, bool]] = []
    pairs = [
        ('dnp', base.dnp, desired.dnp),
        ('exclude_from_sim', base.exclude_from_sim, desired.exclude_from_sim),
        ('in_bom', base.excluded_from_bom, desired.excluded_from_bom),
        ('on_board', base.excluded_from_board, desired.excluded_from_board),
        ('in_pos_files', base.excluded_from_pos, desired.excluded_from_pos),
    ]
    for tag, b, d in pairs:
        if b != d:
            flags.append((tag, d))
    fields: Dict[str, str] = {}
    all_names = set(base.fields) | set(desired.fields)
    for name in sorted(all_names):
        if name not in base.fields:
            raise VariantPromoterError(
                f"Variant introduces field {name!r} that does not exist in the base object; refusing to synthesize field geometry."
            )
        if desired.fields.get(name, '') != base.fields.get(name, ''):
            fields[name] = desired.fields.get(name, '')
    return flags, fields


def _render_variant(name: str, base: State, desired: State, kind: str, version: int, indent: str, eol: str = '\n') -> str:
    flags, fields = _state_diff(base, desired, kind)
    child = indent + '  '
    lines = [indent + '(variant', child + f'(name {_q(name)})']
    for tag, internal in flags:
        lines.append(child + f'({tag} {_variant_flag_text(tag, internal, version)})')
    for fname, fvalue in fields.items():
        lines.append(child + f'(field (name {_q(fname)}) (value {_q(fvalue)}))')
    lines.append(indent + ')')
    return eol.join(lines)


def _desired_base_edits(sch: ParsedSch, obj: ObjectInfo, new_base: State, edits: List[Edit], summary: List[str]) -> None:
    text = sch.text
    old = obj.base
    # Properties: replace only the value token, preserving all geometry/effects.
    if set(new_base.fields) != set(old.fields):
        raise VariantPromoterError(
            f"{sch.path.name}: {obj.kind} {obj.label}: selected variant changes the set of fields; unsupported safely."
        )
    for name in sorted(old.fields):
        if old.fields[name] != new_base.fields[name]:
            pnode = obj.property_nodes.get(name)
            if not pnode:
                raise VariantPromoterError(f"Missing base property node {name!r}")
            _, _, tok = _property_parts(pnode)
            if not tok:
                raise VariantPromoterError(f"Malformed property {name!r}")
            edits.append(Edit(tok.start, tok.end, _q(new_base.fields[name]), f"base field {name}"))
            summary.append(f"{sch.path.name}: {obj.kind} {obj.label}: {name}: {old.fields[name]!r} -> {new_base.fields[name]!r}")

    attr = {
        'dnp': (old.dnp, new_base.dnp),
        'exclude_from_sim': (old.exclude_from_sim, new_base.exclude_from_sim),
        'in_bom': (old.excluded_from_bom, new_base.excluded_from_bom),
        'on_board': (old.excluded_from_board, new_base.excluded_from_board),
        'in_pos_files': (old.excluded_from_pos, new_base.excluded_from_pos),
    }
    inserts: List[str] = []
    insert_pos: Optional[int] = None
    child_indent = _child_indent(text, obj.node)
    eol = _eol(text)
    for tag, (before, after) in attr.items():
        if before == after:
            continue
        if obj.kind == 'sheet' and tag == 'in_pos_files':
            raise VariantPromoterError(
                f"{sch.path.name}: sheet {obj.label}: selected variant changes in_pos_files, which cannot be promoted to a KiCad 10 base sheet."
            )
        n = obj.node.child_node(tag)
        if tag in ('dnp', 'exclude_from_sim'):
            raw = 'yes' if after else 'no'
        else:
            raw = 'no' if after else 'yes'
        if n and n.scalar_token(0):
            t = n.scalar_token(0)
            edits.append(Edit(t.start, t.end, raw, f"base {tag}"))
        else:
            # Insert a top-level object attribute before first property/uuid/instances.
            if insert_pos is None:
                candidates = [c.start for c in obj.node.child_nodes() if c.head in ('uuid', 'property', 'instances')]
                insert_pos = min(candidates) if candidates else _closing_line_start(text, obj.node)
            inserts.append(child_indent + f'({tag} {raw})' + eol)
        summary.append(f"{sch.path.name}: {obj.kind} {obj.label}: {tag} changed in Default")
    if inserts and insert_pos is not None:
        edits.append(Edit(insert_pos, insert_pos, ''.join(inserts), "insert base flags"))


def _apply_edits(text: str, edits: Sequence[Edit]) -> str:
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    prev_end = -1
    for e in ordered:
        if e.start < prev_end:
            raise VariantPromoterError(f"Internal error: overlapping edits near {e.why}")
        prev_end = max(prev_end, e.end)
    out = text
    # Preserve insertion ordering for same position by applying in reverse list order after sorting.
    for e in sorted(edits, key=lambda e: (e.start, e.end), reverse=True):
        out = out[:e.start] + e.replacement + out[e.end:]
    return out


def _project_names_in_sch(sch: ParsedSch) -> set[str]:
    names: set[str] = set()
    for obj in sch.objects:
        for inst in obj.instances:
            if inst.project_name:
                names.add(inst.project_name)
    return names


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _backup_name(path: Path, stamp: str) -> Path:
    return path.with_name(path.name + f'.variant-manager.{stamp}.bak')


def _atomic_write(path: Path, text: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def detect_variants(root_sch: Path) -> Tuple[List[str], Optional[Path], int]:
    root_sch = Path(root_sch).resolve()
    pro = find_project_file(root_sch)
    pnames, _, project_data, _ = load_project_variants(pro)
    schematics = discover_hierarchy(root_sch, pro, project_data)
    names = set(pnames)
    for sch in schematics:
        names.update(sch.variant_names)
    return sorted(names, key=str.casefold), pro, len(schematics)



# ---------- advanced variant management / analysis ----------

DEFAULT_VARIANT = '<Default>'


@dataclasses.dataclass
class ChangeRecord:
    category: str
    item: str
    property: str
    before: str
    after: str
    file: str = ''
    instance: str = ''


@dataclasses.dataclass
class VariantStats:
    name: str
    total_instances: int = 0
    differing_instances: int = 0
    dnp_instances: int = 0
    bom_excluded_instances: int = 0
    pos_excluded_instances: int = 0
    value_differences: int = 0
    footprint_differences: int = 0
    field_differences: int = 0
    flag_differences: int = 0


@dataclasses.dataclass
class ProjectAnalysis:
    root: Path
    project_file: Optional[Path]
    schematic_count: int
    symbol_instances: int
    sheet_instances: int
    variant_names: List[str]
    stats: List[VariantStats]
    warnings: List[str]


@dataclasses.dataclass
class VariantPlan:
    source_root: Path
    project_file: Optional[Path]
    operation: str
    title: str
    schematic_files: List[PlannedFile]
    project_old_sha256: Optional[str]
    project_new_text: Optional[str]
    variants_before: List[str]
    variants_after: List[str]
    summary: List[str]
    changes: List[ChangeRecord]


def _is_default_name(name: str) -> bool:
    return (name or '').strip().casefold() in {
        'default', '<default>', '<default variant>', 'default variant'
    }


def _validate_new_variant_name(name: str) -> str:
    name = (name or '').strip()
    if not name:
        raise VariantPromoterError('Variant name cannot be empty.')
    if _is_default_name(name):
        raise VariantPromoterError(f'{DEFAULT_VARIANT} is reserved and cannot be used as a named variant.')
    if '\n' in name or '\r' in name:
        raise VariantPromoterError('Variant names cannot contain newlines.')
    return name


def _project_context(root_sch: Path):
    root_sch = Path(root_sch).expanduser().resolve()
    if root_sch.suffix.lower() != '.kicad_sch':
        raise VariantPromoterError('Select a root .kicad_sch file.')
    if not root_sch.exists():
        raise VariantPromoterError(f'Schematic does not exist: {root_sch}')
    project_file = find_project_file(root_sch)
    project_names, project_entries, project_data, project_hash = load_project_variants(project_file)
    schematics = discover_hierarchy(root_sch, project_file, project_data)
    all_names: set[str] = set(project_names)
    for sch in schematics:
        all_names.update(sch.variant_names)
    ordered: List[str] = []
    seen: set[str] = set()
    for name in project_names + sorted(all_names - set(project_names), key=str.casefold):
        cf = name.casefold()
        if cf in seen:
            # A case-only duplicate is ambiguous in a human-facing manager.
            other = next((x for x in ordered if x.casefold() == cf), name)
            if other != name:
                raise VariantPromoterError(f'Variants differ only by case: {other!r} and {name!r}')
            continue
        seen.add(cf)
        ordered.append(name)
    return root_sch, project_file, project_entries, project_data, project_hash, schematics, ordered


def _resolve_variant(name: str, names: Sequence[str], allow_default: bool = True) -> str:
    if allow_default and _is_default_name(name):
        return DEFAULT_VARIANT
    by_cf = {n.casefold(): n for n in names}
    actual = by_cf.get((name or '').strip().casefold())
    if actual is None:
        choices = ', '.join(names) or '(none)'
        raise VariantPromoterError(f'Variant {name!r} was not found. Detected: {choices}')
    return actual


def _state_for(base: State, inst: InstanceInfo, variant: str, version: int) -> State:
    if variant == DEFAULT_VARIANT:
        return base.clone()
    return _effective_state(base, inst.variants.get(variant), version)


def _bool_text(v: bool) -> str:
    return 'Yes' if v else 'No'


def _state_change_records(
    before: State,
    after: State,
    *,
    file: str,
    item: str,
    instance: str = '',
    category_prefix: str = '',
) -> List[ChangeRecord]:
    out: List[ChangeRecord] = []
    flag_specs = [
        ('DNP', before.dnp, after.dnp),
        ('Exclude from simulation', before.exclude_from_sim, after.exclude_from_sim),
        ('Exclude from BOM', before.excluded_from_bom, after.excluded_from_bom),
        ('Exclude from board', before.excluded_from_board, after.excluded_from_board),
        ('Exclude from position files', before.excluded_from_pos, after.excluded_from_pos),
    ]
    cat_flags = (category_prefix + 'Flags').strip()
    cat_fields = (category_prefix + 'Fields').strip()
    for prop, a, b in flag_specs:
        if a != b:
            out.append(ChangeRecord(cat_flags, item, prop, _bool_text(a), _bool_text(b), file, instance))
    for name in sorted(set(before.fields) | set(after.fields), key=str.casefold):
        a = before.fields.get(name, '')
        b = after.fields.get(name, '')
        if a != b:
            out.append(ChangeRecord(cat_fields, item, name, a, b, file, instance))
    return out


def _build_project_variant_text(
    project_file: Optional[Path],
    project_data: Optional[dict],
    project_entries: Dict[str, dict],
    variant_sources: Sequence[Tuple[str, str]],
    metadata_overrides: Optional[Dict[str, dict]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    if not project_file or project_data is None:
        return None, None
    metadata_overrides = metadata_overrides or {}
    data = copy.deepcopy(project_data)
    sch_meta = data.setdefault('schematic', {})
    entries_cf = {k.casefold(): copy.deepcopy(v) for k, v in project_entries.items()}
    new_entries: List[dict] = []
    for new_name, source in variant_sources:
        override = metadata_overrides.get(new_name)
        if override is not None:
            entry = copy.deepcopy(override)
        elif source != DEFAULT_VARIANT and source.casefold() in entries_cf:
            entry = copy.deepcopy(entries_cf[source.casefold()])
        elif new_name.casefold() in entries_cf:
            entry = copy.deepcopy(entries_cf[new_name.casefold()])
        else:
            entry = {'name': new_name}
        entry['name'] = new_name
        new_entries.append(entry)
    sch_meta['variants'] = new_entries
    raw_bytes = project_file.read_bytes()
    try:
        raw = raw_bytes.decode('utf-8')
    except UnicodeDecodeError as e:
        raise VariantPromoterError(f'{project_file.name}: not UTF-8: {e}') from e
    eol = _eol(raw)
    new_text = json.dumps(data, indent=2, ensure_ascii=False).replace('\n', eol) + eol
    if new_text == raw:
        return None, None
    return new_text, hashlib.sha256(raw_bytes).hexdigest()


def _plan_transform(
    root_sch: Path,
    *,
    operation: str,
    title: str,
    new_default_source: str,
    variant_sources: Sequence[Tuple[str, str]],
    summary_head: str,
    high_level_changes: Optional[List[ChangeRecord]] = None,
    metadata_overrides: Optional[Dict[str, dict]] = None,
) -> VariantPlan:
    """Generic loss-safe semantic transform.

    ``variant_sources`` maps each named variant *after* the operation to the
    pre-operation state it must preserve.  A source may be another named
    variant or DEFAULT_VARIANT.  ``new_default_source`` similarly selects the
    pre-operation state that becomes the new base/Default.

    Existing variant blocks are regenerated from semantic states.  This is
    intentionally more conservative than textual renaming because it also
    cleans stale/redundant overrides and guarantees that clone/swap/rebase
    operations preserve effective behavior.
    """
    (
        root_sch, project_file, project_entries, project_data, project_hash,
        schematics, old_names,
    ) = _project_context(root_sch)

    new_default_source = _resolve_variant(new_default_source, old_names, allow_default=True)

    normalized_sources: List[Tuple[str, str]] = []
    seen_after: Dict[str, str] = {}
    for new_name, source in variant_sources:
        new_name = _validate_new_variant_name(new_name)
        cf = new_name.casefold()
        if cf in seen_after:
            raise VariantPromoterError(
                f'Output variants differ only by case or duplicate a name: {seen_after[cf]!r}, {new_name!r}'
            )
        seen_after[cf] = new_name
        source = _resolve_variant(source, old_names, allow_default=True)
        normalized_sources.append((new_name, source))

    # Modifying a shared schematic would also modify the other project's base
    # or variant blocks. Refuse rather than make a surprising cross-project edit.
    for sch in schematics:
        pnames = _project_names_in_sch(sch)
        if len(pnames) > 1:
            raise VariantPromoterError(
                f'{sch.path.name} contains instance data for multiple projects '
                f'({", ".join(sorted(pnames))}). This manager refuses to rewrite shared multi-project schematic data.'
            )

    planned: List[PlannedFile] = []
    changes: List[ChangeRecord] = list(high_level_changes or [])
    anchors_created: set[str] = set()

    for sch in schematics:
        if sch.version < SUPPORTED_MIN_VARIANT_VERSION and sch.variant_names:
            raise VariantPromoterError(
                f'{sch.path.name}: variant blocks in pre-variant file version {sch.version}'
            )
        edits: List[Edit] = []

        for obj in sch.objects:
            if not obj.instances:
                continue

            # Capture all pre-operation effective states before any base edit.
            old_states: Dict[Tuple[int, str], State] = {}
            for idx, inst in enumerate(obj.instances):
                old_states[(idx, DEFAULT_VARIANT)] = obj.base.clone()
                for name in old_names:
                    old_states[(idx, name)] = _effective_state(
                        obj.base, inst.variants.get(name), sch.version
                    )

            # One serialized base object is shared by hierarchical instances,
            # therefore the state chosen as Default must be identical in all.
            new_base_states = [old_states[(idx, new_default_source)] for idx in range(len(obj.instances))]
            sigs = {s.signature() for s in new_base_states}
            if len(sigs) > 1:
                inst_names = [inst.reference or inst.path_id or f'instance {i+1}' for i, inst in enumerate(obj.instances)]
                raise VariantPromoterError(
                    f'{sch.path.name}: cannot make {new_default_source!r} Default for {obj.kind} {obj.label} '
                    f'({obj.uuid}) because hierarchical instances differ: {", ".join(inst_names)}.'
                )
            new_base = new_base_states[0]
            if new_base.signature() != obj.base.signature():
                changes.extend(_state_change_records(
                    obj.base, new_base,
                    file=sch.path.name,
                    item=obj.label,
                    category_prefix='Default ',
                ))
            _desired_base_edits(sch, obj, new_base, edits, [])

            for idx, inst in enumerate(obj.instances):
                # Remove all existing blocks and regenerate the exact desired set.
                # This deliberately removes redundant overrides.
                for old_name, vnode in inst.variants.items():
                    edits.append(Edit(vnode.start, vnode.end, '', f'remove old variant block {old_name}'))

                blocks: List[str] = []
                indent = _child_indent(sch.text, inst.path_node)
                eol = _eol(sch.text)
                for new_name, source in normalized_sources:
                    desired = old_states[(idx, source)]
                    flags, fields = _state_diff(new_base, desired, obj.kind)
                    needs_block = bool(flags or fields)
                    # Without .kicad_pro metadata, keep one minimal anchor for a
                    # variant even when it is semantically identical to Default.
                    if needs_block or (project_file is None and new_name not in anchors_created):
                        blocks.append(_render_variant(
                            new_name, new_base, desired, obj.kind, sch.version, indent, eol
                        ))
                        anchors_created.add(new_name)
                if blocks:
                    pos = _closing_line_start(sch.text, inst.path_node)
                    insertion = ''.join(block + eol for block in blocks)
                    edits.append(Edit(pos, pos, insertion, 'insert regenerated variant blocks'))

        if edits:
            new_text = _apply_edits(sch.text, edits)
            reparsed = SExprParser(new_text).parse()
            if reparsed.head != 'kicad_sch':
                raise VariantPromoterError(f'Internal validation failed for {sch.path.name}')
            # Full semantic parse catches unsupported tokens / malformed state.
            fd, temp_path = tempfile.mkstemp(prefix='kvv-', suffix='.kicad_sch')
            os.close(fd)
            try:
                Path(temp_path).write_text(new_text, encoding='utf-8', newline='')
                parse_schematic(Path(temp_path))
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            if new_text != sch.text:
                planned.append(PlannedFile(sch.path, sch.sha256, new_text, edits))

    project_new_text, project_old_hash = _build_project_variant_text(
        project_file, project_data, project_entries, normalized_sources, metadata_overrides
    )
    # Make the review page visually explicit about which physical files are
    # scheduled to change, in addition to semantic component/variant changes.
    for pf in planned:
        changes.append(ChangeRecord(
            'File rewrite', pf.path.name, 'Targeted edits',
            str(len(pf.edits)), 'Rewrite with timestamped backup', pf.path.name
        ))
    if project_file and project_new_text is not None:
        changes.append(ChangeRecord(
            'File rewrite', project_file.name, 'Variant metadata',
            'Current .kicad_pro', 'Updated .kicad_pro with backup', project_file.name
        ))
    after_names = [name for name, _ in normalized_sources]
    summary = [summary_head]
    summary.append(f'Schematic files in project/hierarchy: {len(schematics)}.')
    summary.append(f'Named variants: {len(old_names)} -> {len(after_names)}.')
    summary.append(
        f'Files to rewrite: {len(planned) + (1 if project_new_text is not None else 0)} '
        f'({len(planned)} schematic, {1 if project_new_text is not None else 0} project metadata).'
    )
    if changes:
        summary.append(f'Visible semantic/management changes in preview: {len(changes)}.')
    else:
        summary.append('No effective component values/flags change; this operation only normalizes serialized overrides/metadata.')
    summary.append('Timestamped backups are created before the first write, and source hashes are rechecked at Apply.')

    return VariantPlan(
        source_root=root_sch,
        project_file=project_file,
        operation=operation,
        title=title,
        schematic_files=planned,
        project_old_sha256=project_old_hash,
        project_new_text=project_new_text,
        variants_before=old_names,
        variants_after=after_names,
        summary=summary,
        changes=changes,
    )


def plan_promote_variant(root_sch: Path, selected_variant: str, keep_source: bool = False) -> VariantPlan:
    _, _, _, _, _, _, old_names = _project_context(root_sch)
    selected = _resolve_variant(selected_variant, old_names, allow_default=False)
    sources: List[Tuple[str, str]] = []
    for name in old_names:
        if name == selected:
            if keep_source:
                sources.append((name, selected))
        else:
            sources.append((name, name))
    high = [ChangeRecord('Variant', selected, 'Operation', selected, DEFAULT_VARIANT)]
    return _plan_transform(
        root_sch,
        operation='promote',
        title=f'Set {selected} as Default',
        new_default_source=selected,
        variant_sources=sources,
        summary_head=(
            f'Make named variant {selected!r} the new Default. Other variants are rebased '
            'so their effective values and fitted/DNP behavior remain unchanged.'
        ),
        high_level_changes=high,
    )


def plan_swap_default(root_sch: Path, selected_variant: str, old_default_name: str) -> VariantPlan:
    _, _, _, _, _, _, old_names = _project_context(root_sch)
    selected = _resolve_variant(selected_variant, old_names, allow_default=False)
    old_default_name = _validate_new_variant_name(old_default_name)
    if any(n.casefold() == old_default_name.casefold() and n != selected for n in old_names):
        raise VariantPromoterError(f'Variant {old_default_name!r} already exists.')
    sources: List[Tuple[str, str]] = []
    for name in old_names:
        if name == selected:
            sources.append((old_default_name, DEFAULT_VARIANT))
        else:
            sources.append((name, name))
    metadata = {
        old_default_name: {
            'name': old_default_name,
            'description': f'Previous Default preserved when {selected} was made Default',
        }
    }
    high = [
        ChangeRecord('Variant', selected, 'New Default', selected, DEFAULT_VARIANT),
        ChangeRecord('Variant', old_default_name, 'Preserve old Default', DEFAULT_VARIANT, old_default_name),
    ]
    return _plan_transform(
        root_sch,
        operation='swap_default',
        title=f'Swap {selected} with Default',
        new_default_source=selected,
        variant_sources=sources,
        summary_head=(
            f'Make {selected!r} Default and preserve the previous Default as named variant '
            f'{old_default_name!r}. Other variants retain their pre-swap effective state.'
        ),
        high_level_changes=high,
        metadata_overrides=metadata,
    )


def plan_rename_variant(root_sch: Path, selected_variant: str, new_name: str) -> VariantPlan:
    _, _, _, _, _, _, old_names = _project_context(root_sch)
    selected = _resolve_variant(selected_variant, old_names, allow_default=False)
    new_name = _validate_new_variant_name(new_name)
    if new_name.casefold() != selected.casefold() and any(n.casefold() == new_name.casefold() for n in old_names):
        raise VariantPromoterError(f'Variant {new_name!r} already exists.')
    sources = [(new_name if n == selected else n, n) for n in old_names]
    high = [ChangeRecord('Variant', selected, 'Name', selected, new_name)]
    return _plan_transform(
        root_sch,
        operation='rename',
        title=f'Rename {selected} to {new_name}',
        new_default_source=DEFAULT_VARIANT,
        variant_sources=sources,
        summary_head=f'Rename variant {selected!r} to {new_name!r} without changing its effective configuration.',
        high_level_changes=high,
    )


def plan_duplicate_variant(root_sch: Path, source_variant: str, new_name: str) -> VariantPlan:
    _, _, _, _, _, _, old_names = _project_context(root_sch)
    source = _resolve_variant(source_variant, old_names, allow_default=True)
    new_name = _validate_new_variant_name(new_name)
    if any(n.casefold() == new_name.casefold() for n in old_names):
        raise VariantPromoterError(f'Variant {new_name!r} already exists.')
    sources = [(n, n) for n in old_names] + [(new_name, source)]
    high = [ChangeRecord('Variant', new_name, 'Clone from', source, new_name)]
    metadata = {}
    if source == DEFAULT_VARIANT:
        metadata[new_name] = {'name': new_name, 'description': 'Created from Default'}
    return _plan_transform(
        root_sch,
        operation='duplicate',
        title=f'Duplicate {source} as {new_name}',
        new_default_source=DEFAULT_VARIANT,
        variant_sources=sources,
        summary_head=f'Create variant {new_name!r} as an exact effective copy of {source!r}.',
        high_level_changes=high,
        metadata_overrides=metadata,
    )


def plan_delete_variant(root_sch: Path, selected_variant: str) -> VariantPlan:
    _, _, _, _, _, _, old_names = _project_context(root_sch)
    selected = _resolve_variant(selected_variant, old_names, allow_default=False)
    sources = [(n, n) for n in old_names if n != selected]
    high = [ChangeRecord('Variant', selected, 'Delete', selected, '(removed)')]
    return _plan_transform(
        root_sch,
        operation='delete',
        title=f'Delete {selected}',
        new_default_source=DEFAULT_VARIANT,
        variant_sources=sources,
        summary_head=f'Delete named variant {selected!r}. Default and all remaining variants keep their effective state.',
        high_level_changes=high,
    )


def plan_clean_overrides(root_sch: Path) -> VariantPlan:
    _, _, _, _, _, _, old_names = _project_context(root_sch)
    sources = [(n, n) for n in old_names]
    high = [ChangeRecord('Maintenance', 'All variants', 'Overrides', 'Current serialization', 'Minimal semantic overrides')]
    return _plan_transform(
        root_sch,
        operation='clean',
        title='Clean redundant variant overrides',
        new_default_source=DEFAULT_VARIANT,
        variant_sources=sources,
        summary_head=(
            'Rebuild all named variant blocks against the current Default, removing redundant overrides '
            'while preserving every variantÃ¢â‚¬â„¢s effective state.'
        ),
        high_level_changes=high,
    )


def analyze_project(root_sch: Path) -> ProjectAnalysis:
    root, project_file, _, project_data, _, schematics, names = _project_context(root_sch)
    stats_by_name: Dict[str, VariantStats] = {DEFAULT_VARIANT: VariantStats(DEFAULT_VARIANT)}
    for name in names:
        stats_by_name[name] = VariantStats(name)
    symbol_instances = 0
    sheet_instances = 0
    warnings: List[str] = []
    if project_file is None:
        warnings.append('No matching .kicad_pro was found; named variants are inferred only from schematic blocks.')

    for sch in schematics:
        if sch.version < SUPPORTED_MIN_VARIANT_VERSION:
            warnings.append(f'{sch.path.name} uses pre-variant schematic format {sch.version}.')
        for obj in sch.objects:
            if obj.kind == 'symbol':
                symbol_instances += len(obj.instances)
            else:
                sheet_instances += len(obj.instances)
            for inst in obj.instances:
                default = obj.base
                for name in [DEFAULT_VARIANT] + names:
                    st = default if name == DEFAULT_VARIANT else _effective_state(default, inst.variants.get(name), sch.version)
                    vs = stats_by_name[name]
                    vs.total_instances += 1
                    if st.dnp:
                        vs.dnp_instances += 1
                    if st.excluded_from_bom:
                        vs.bom_excluded_instances += 1
                    if st.excluded_from_pos:
                        vs.pos_excluded_instances += 1
                    if name != DEFAULT_VARIANT:
                        any_diff = False
                        flag_pairs = [
                            (default.dnp, st.dnp),
                            (default.exclude_from_sim, st.exclude_from_sim),
                            (default.excluded_from_bom, st.excluded_from_bom),
                            (default.excluded_from_board, st.excluded_from_board),
                            (default.excluded_from_pos, st.excluded_from_pos),
                        ]
                        flag_count = sum(1 for a, b in flag_pairs if a != b)
                        vs.flag_differences += flag_count
                        any_diff |= flag_count > 0
                        for field_name in set(default.fields) | set(st.fields):
                            if default.fields.get(field_name, '') != st.fields.get(field_name, ''):
                                vs.field_differences += 1
                                any_diff = True
                                if field_name == 'Value':
                                    vs.value_differences += 1
                                elif field_name == 'Footprint':
                                    vs.footprint_differences += 1
                        if any_diff:
                            vs.differing_instances += 1

    stats = [stats_by_name[DEFAULT_VARIANT]] + [stats_by_name[n] for n in names]
    return ProjectAnalysis(
        root=root,
        project_file=project_file,
        schematic_count=len(schematics),
        symbol_instances=symbol_instances,
        sheet_instances=sheet_instances,
        variant_names=names,
        stats=stats,
        warnings=warnings,
    )


def compare_variants(root_sch: Path, left_variant: str, right_variant: str) -> List[ChangeRecord]:
    _, _, _, _, _, schematics, names = _project_context(root_sch)
    left = _resolve_variant(left_variant, names, allow_default=True)
    right = _resolve_variant(right_variant, names, allow_default=True)
    out: List[ChangeRecord] = []
    for sch in schematics:
        for obj in sch.objects:
            for inst in obj.instances:
                a = _state_for(obj.base, inst, left, sch.version)
                b = _state_for(obj.base, inst, right, sch.version)
                item = inst.reference or obj.label or obj.uuid
                out.extend(_state_change_records(
                    a, b,
                    file=sch.path.name,
                    item=item,
                    instance=inst.path_id,
                    category_prefix='',
                ))
    return out


def export_changes_csv(records: Sequence[ChangeRecord], path: Path) -> None:
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Category', 'Item', 'Property', 'Before', 'After', 'File', 'Instance'])
        for r in records:
            writer.writerow([r.category, r.item, r.property, r.before, r.after, r.file, r.instance])


# ---------- guided GUI ----------
