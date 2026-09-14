#!/usr/bin/env python3
"""KiCad 10 Design Variant Workbench.

Standalone, standard-library-only tool with a Tkinter GUI and CLI, plus the
engine bundled into the KiCad IPC launcher.  The Workbench keeps the original
Variant → Default merge/rebase operation as a dedicated workflow and adds a
variant matrix, health checks, safe substitution editing, PCB sync auditing,
comparison/management tools, and manufacturing release generation.

Write operations are deliberately conservative: they preview semantic changes,
validate generated S-expressions, re-check exact file hashes, create timestamped
backups, and atomically replace files.  Unsupported or ambiguous structures are
rejected rather than guessed at.
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
import subprocess
import shlex
import zipfile
import sys
import tempfile
import webbrowser
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

APP_NAME = "WayriCAD Design Variant Workbench"
APP_VERSION = "3.0.0"
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
                        buf.append(mapping.get(esc, esc))
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
            if isinstance(entry, dict) and isinstance(entry.get('name'), str):
                name = entry['name']
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
            child = _resolve_sheet_path(p.parent, raw)
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


def plan_promotion(root_sch: Path, selected_variant: str, keep_source: bool = False) -> PromotionPlan:
    if not selected_variant or selected_variant.casefold() in {'<default>', '<default variant>', 'default'}:
        raise VariantPromoterError("Choose a named variant, not <Default>.")
    root_sch = Path(root_sch).resolve()
    if root_sch.suffix.lower() != '.kicad_sch':
        raise VariantPromoterError("Select the root .kicad_sch file.")

    project_file = find_project_file(root_sch)
    project_names, project_entries, project_data, project_hash = load_project_variants(project_file)
    schematics = discover_hierarchy(root_sch, project_file, project_data)

    all_names: set[str] = set(project_names)
    for sch in schematics:
        all_names.update(sch.variant_names)
    # Case-insensitive convenience lookup while preserving the exact serialized name.
    actual_by_cf: Dict[str, str] = {}
    for n in sorted(all_names):
        cf = n.casefold()
        if cf in actual_by_cf and actual_by_cf[cf] != n:
            raise VariantPromoterError(f"Variants differ only by case: {actual_by_cf[cf]!r} and {n!r}")
        actual_by_cf[cf] = n
    actual = actual_by_cf.get(selected_variant.casefold())
    if actual is None:
        raise VariantPromoterError(
            f"Variant {selected_variant!r} was not found. Detected: {', '.join(sorted(all_names)) or '(none)'}"
        )
    selected_variant = actual

    # Shared-by-multiple-projects files are dangerous because Default itself is shared.
    for sch in schematics:
        pnames = _project_names_in_sch(sch)
        if len(pnames) > 1:
            raise VariantPromoterError(
                f"{sch.path.name} contains instance data for multiple projects ({', '.join(sorted(pnames))}). "
                "Changing its Default would affect those projects too; this tool refuses that case."
            )

    planned: List[PlannedFile] = []
    summary: List[str] = []
    # Keep the .kicad_pro order stable, then append names found only in schematic blocks.
    variant_list: List[str] = []
    seen_variants: set[str] = set()
    for n in project_names + sorted(all_names - set(project_names), key=str.casefold):
        if n not in seen_variants:
            seen_variants.add(n)
            variant_list.append(n)

    for sch in schematics:
        if sch.version < SUPPORTED_MIN_VARIANT_VERSION:
            # An older file can exist in a hierarchy, but it cannot contain variants. Leave it alone.
            if sch.variant_names:
                raise VariantPromoterError(f"{sch.path.name}: variant blocks in pre-variant file version {sch.version}")
        edits: List[Edit] = []

        for obj in sch.objects:
            if not obj.instances:
                continue
            # Snapshot the effective state of all variants for every instance before changing base.
            effective: Dict[Tuple[int, str], State] = {}
            for idx, inst in enumerate(obj.instances):
                for vname in variant_list:
                    effective[(idx, vname)] = _effective_state(obj.base, inst.variants.get(vname), sch.version)

            # The selected variant becomes one base state shared by every instance of this object.
            target_states = [effective[(idx, selected_variant)] for idx in range(len(obj.instances))]
            sigs = {s.signature() for s in target_states}
            if len(sigs) > 1:
                details = []
                for idx, inst in enumerate(obj.instances):
                    details.append(inst.reference or inst.path_id or f"instance {idx+1}")
                raise VariantPromoterError(
                    f"{sch.path.name}: cannot promote {obj.kind} {obj.label} ({obj.uuid}). "
                    f"The selected variant has different effective values in hierarchical instances: {', '.join(details)}. "
                    "A single Default base object cannot represent those instance-specific values."
                )
            new_base = target_states[0]
            _desired_base_edits(sch, obj, new_base, edits, summary)

            # Rebase named variants per instance against the new Default while preserving old behavior.
            for idx, inst in enumerate(obj.instances):
                existing = inst.variants
                replacements: Dict[str, Optional[str]] = {}
                missing_blocks: List[str] = []
                path_indent = _child_indent(sch.text, inst.path_node)

                for vname in variant_list:
                    vnode = existing.get(vname)
                    if vname == selected_variant:
                        if keep_source:
                            desired = new_base
                            rendered = _render_variant(vname, new_base, desired, obj.kind, sch.version,
                                                       _line_indent(sch.text, vnode.start) if vnode else path_indent, _eol(sch.text))
                            if vnode:
                                replacements[vname] = rendered
                            # No block is necessary if project metadata will preserve the empty variant.
                            elif project_file is None:
                                missing_blocks.append(rendered)
                        else:
                            if vnode:
                                replacements[vname] = None
                        continue

                    desired = effective[(idx, vname)]
                    flags, fields = _state_diff(new_base, desired, obj.kind)
                    needs_block = bool(flags or fields)
                    if needs_block:
                        rendered = _render_variant(vname, new_base, desired, obj.kind, sch.version,
                                                   _line_indent(sch.text, vnode.start) if vnode else path_indent, _eol(sch.text))
                        if vnode:
                            replacements[vname] = rendered
                        else:
                            missing_blocks.append(rendered)
                    elif vnode:
                        if project_file is None:
                            # Without .kicad_pro metadata, keep a minimal schematic anchor so the
                            # global variant name does not vanish merely because this override became redundant.
                            replacements[vname] = _render_variant(
                                vname, new_base, new_base, obj.kind, sch.version,
                                _line_indent(sch.text, vnode.start),
                                _eol(sch.text),
                            )
                        else:
                            # Project metadata preserves the name; the redundant override can disappear.
                            replacements[vname] = None

                for vname, repl in replacements.items():
                    vnode = existing[vname]
                    edits.append(Edit(vnode.start, vnode.end, repl or '', f"rebase variant {vname}"))
                if missing_blocks:
                    pos = _closing_line_start(sch.text, inst.path_node)
                    eol = _eol(sch.text)
                    insertion = ''.join(block + eol for block in missing_blocks)
                    edits.append(Edit(pos, pos, insertion, "insert rebased variant overrides"))

        if edits:
            new_text = _apply_edits(sch.text, edits)
            # Parse the result immediately: syntax safety check before any disk write.
            reparsed = SExprParser(new_text).parse()
            if reparsed.head != 'kicad_sch':
                raise VariantPromoterError(f"Internal validation failed for {sch.path.name}")
            planned.append(PlannedFile(sch.path, sch.sha256, new_text, edits))

    # Update the project-level authoritative variant metadata list.
    project_new_text: Optional[str] = None
    after_names = [n for n in variant_list if keep_source or n != selected_variant]
    if project_file and project_data is not None:
        data = copy.deepcopy(project_data)
        sch_meta = data.setdefault('schematic', {})
        old_entries_order: List[dict] = []
        for e in sch_meta.get('variants', []) or []:
            if isinstance(e, dict) and isinstance(e.get('name'), str):
                old_entries_order.append(copy.deepcopy(e))
        entry_by_cf = {e['name'].casefold(): e for e in old_entries_order}
        new_entries: List[dict] = []
        for name in after_names:
            e = entry_by_cf.get(name.casefold(), {'name': name})
            e['name'] = name
            new_entries.append(e)
        sch_meta['variants'] = new_entries
        old_raw_bytes = project_file.read_bytes()
        try:
            old_raw = old_raw_bytes.decode('utf-8')
        except UnicodeDecodeError as e:
            raise VariantPromoterError(f"{project_file.name}: not UTF-8: {e}") from e
        project_eol = _eol(old_raw)
        project_new_text = json.dumps(data, indent=2, ensure_ascii=False).replace('\n', project_eol) + project_eol
        if project_new_text == old_raw:
            project_new_text = None
            project_hash = None

    if not planned and project_new_text is None:
        summary.append("No serialized changes are required; the selected variant already matches Default or is metadata-only.")

    summary.insert(0, f"Promote variant {selected_variant!r} to Default across {len(schematics)} schematic file(s).")
    if keep_source:
        summary.append(f"Named variant {selected_variant!r} will be kept as an empty/equivalent variant.")
    else:
        summary.append(f"Named variant {selected_variant!r} will be removed after its state becomes Default.")
    summary.append("All other named variants are rebased to preserve their pre-promotion effective state.")

    return PromotionPlan(
        source_root=root_sch,
        project_file=project_file,
        selected_variant=selected_variant,
        keep_source=keep_source,
        schematic_files=planned,
        project_old_sha256=project_hash,
        project_new_text=project_new_text,
        variants_before=variant_list,
        variants_after=after_names,
        summary=summary,
    )


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


def project_lock_files(paths: Sequence[Path]) -> List[Path]:
    """Return KiCad editor lock files beside any file in a write plan."""
    found: set[Path] = set()
    for directory in {Path(path).resolve().parent for path in paths}:
        for pattern in ("*.lck", ".*.lck", "~*.lck", "*.lock"):
            found.update(path for path in directory.glob(pattern) if path.is_file())
    return sorted(found, key=lambda path: str(path).casefold())


def apply_plan(plan: PromotionPlan) -> List[Path]:
    write_paths = [pf.path for pf in plan.schematic_files]
    if plan.project_file and plan.project_new_text is not None:
        write_paths.append(plan.project_file)
    locks = project_lock_files(write_paths)
    if locks:
        raise VariantPromoterError(
            "KiCad project lock files are present. Save and close the editors, then preview again before applying:\n"
            + "\n".join(str(path) for path in locks)
        )
    # Re-check every input before touching anything.
    for pf in plan.schematic_files:
        if _hash_file(pf.path) != pf.old_sha256:
            raise VariantPromoterError(f"{pf.path.name} changed since preview. Preview again before applying.")
    if plan.project_file and plan.project_new_text is not None and plan.project_old_sha256:
        if _hash_file(plan.project_file) != plan.project_old_sha256:
            raise VariantPromoterError(f"{plan.project_file.name} changed since preview. Preview again before applying.")

    stamp = _dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    changed_paths = [pf.path for pf in plan.schematic_files]
    if plan.project_file and plan.project_new_text is not None:
        changed_paths.append(plan.project_file)

    backups: List[Path] = []
    for p in changed_paths:
        b = _backup_name(p, stamp)
        shutil.copy2(p, b)
        backups.append(b)

    # All backups exist before the first write.
    try:
        for pf in plan.schematic_files:
            _atomic_write(pf.path, pf.new_text)
        if plan.project_file and plan.project_new_text is not None:
            _atomic_write(plan.project_file, plan.project_new_text)
    except Exception as e:
        # Best-effort rollback from our just-created backups.
        for p, b in zip(changed_paths, backups):
            try:
                shutil.copy2(b, p)
            except OSError:
                pass
        raise VariantPromoterError(f"Write failed and rollback was attempted: {e}") from e
    return backups


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
            'while preserving every variant’s effective state.'
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



# ---------- workbench matrix / lint / substitution / release ----------

@dataclasses.dataclass
class MatrixRow:
    key: str
    file: str
    kind: str
    uuid: str
    instance_path: str
    reference: str
    base: State
    states: Dict[str, State]


@dataclasses.dataclass
class VariantPatch:
    """A semantic edit to one symbol/sheet instance in one variant.

    ``field_updates`` sets effective field values.  An empty string is a real
    value, not a request to delete a field.  Flags that are ``None`` are left
    unchanged.
    """
    file: str
    uuid: str
    instance_path: str
    variant: str
    field_updates: Dict[str, str] = dataclasses.field(default_factory=dict)
    dnp: Optional[bool] = None
    exclude_from_sim: Optional[bool] = None
    excluded_from_bom: Optional[bool] = None
    excluded_from_board: Optional[bool] = None
    excluded_from_pos: Optional[bool] = None


@dataclasses.dataclass
class LintIssue:
    severity: str  # ERROR | WARNING | INFO
    code: str
    item: str
    message: str
    file: str = ''
    variant: str = ''


@dataclasses.dataclass
class SyncIssue:
    """One schematic ↔ PCB variant synchronization finding."""
    severity: str  # ERROR | WARNING | INFO
    reference: str
    variant: str
    property: str
    schematic: str
    pcb: str
    message: str


@dataclasses.dataclass
class PcbFootprintInfo:
    reference: str
    uuid: str
    library_id: str
    base: State
    variants: Dict[str, State]


@dataclasses.dataclass
class ParsedBoard:
    path: Path
    version: int
    variant_names: List[str]  # board-level metadata
    serialized_variant_names: List[str]  # footprint-level blocks
    footprints: List[PcbFootprintInfo]
    sha256: str


def _sexpr_bool(node: Optional[Node], default: bool = True) -> bool:
    """Parse KiCad's normalized/legacy maybe-absent boolean form."""
    if node is None:
        return default
    raw = node.scalar(0)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {'yes', 'true', '1', 'on'}:
        return True
    if value in {'no', 'false', '0', 'off'}:
        return False
    raise VariantPromoterError(f'Unsupported boolean value {raw!r} in PCB file.')


def _pcb_variant_effective(base: State, vnode: Node) -> Tuple[str, State]:
    name_node = vnode.child_node('name')
    name = (name_node.scalar(0, '') if name_node else '') or ''
    st = base.clone()
    dn = vnode.child_node('dnp')
    if dn is not None:
        st.dnp = _sexpr_bool(dn)
    bn = vnode.child_node('exclude_from_bom')
    if bn is not None:
        st.excluded_from_bom = _sexpr_bool(bn)
    pn = vnode.child_node('exclude_from_pos_files')
    if pn is not None:
        st.excluded_from_pos = _sexpr_bool(pn)
    for fnode in vnode.child_nodes('field'):
        nn = fnode.child_node('name')
        vn = fnode.child_node('value')
        if nn is None:
            continue
        fname = nn.scalar(0, '') or ''
        if not fname:
            continue
        st.fields[fname] = (vn.scalar(0, '') if vn else '') or ''
    return name, st


def parse_board(path: Path) -> ParsedBoard:
    """Read the subset of .kicad_pcb needed for variant sync auditing.

    This is intentionally read-only.  KiCad PCB variants can carry DNP,
    exclude-from-BOM, exclude-from-position, and field overrides.  The audit
    mirrors exactly that safe subset rather than attempting a board rewrite.
    """
    path = Path(path).expanduser().resolve()
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as e:
        raise VariantPromoterError(f'{path.name} is not valid UTF-8: {e}') from e
    root = SExprParser(text).parse()
    if root.head != 'kicad_pcb':
        raise VariantPromoterError(f'{path.name} is not a KiCad PCB file.')
    vn = root.child_node('version')
    try:
        version = int(vn.scalar(0, '0') if vn else 0)
    except (TypeError, ValueError):
        version = 0

    variant_names: List[str] = []
    variants_root = root.child_node('variants')
    if variants_root:
        for vnode in variants_root.child_nodes('variant'):
            nn = vnode.child_node('name')
            name = (nn.scalar(0, '') if nn else '') or ''
            if name and name.casefold() not in {n.casefold() for n in variant_names}:
                variant_names.append(name)

    footprints: List[PcbFootprintInfo] = []
    discovered: List[str] = []
    for fp in root.child_nodes('footprint'):
        library_id = fp.scalar(0, '') or ''
        fields: Dict[str, str] = {'Footprint': library_id}

        # Modern PCB custom fields use (property "Name" "Value" ...).
        for prop in fp.child_nodes('property'):
            name = prop.scalar(0, '') or ''
            value = prop.scalar(1, '') or ''
            if name:
                fields[name] = value

        # Reference and Value are still PCB fields serialized as fp_text.
        for txt in fp.child_nodes('fp_text'):
            kind = (txt.scalar(0, '') or '').casefold()
            value = txt.scalar(1, '') or ''
            if kind == 'reference':
                fields['Reference'] = value
            elif kind == 'value':
                fields['Value'] = value

        attrs = set()
        attr = fp.child_node('attr')
        if attr:
            attrs = {(t.value or '').casefold() for t in attr.scalar_tokens()}
        base = State(
            dnp='dnp' in attrs,
            excluded_from_bom=('exclude_from_bom' in attrs or 'virtual' in attrs),
            excluded_from_pos=('exclude_from_pos_files' in attrs or 'virtual' in attrs),
            fields=fields,
        )
        uuid_node = fp.child_node('uuid') or fp.child_node('tstamp')
        uuid = (uuid_node.scalar(0, '') if uuid_node else '') or ''
        reference = fields.get('Reference', '')
        variants: Dict[str, State] = {}
        for vnode in fp.child_nodes('variant'):
            name, st = _pcb_variant_effective(base, vnode)
            if not name:
                continue
            variants[name] = st
            if name.casefold() not in {n.casefold() for n in discovered}:
                discovered.append(name)
        footprints.append(PcbFootprintInfo(reference, uuid, library_id, base, variants))

    return ParsedBoard(path, version, variant_names, discovered, footprints, hashlib.sha256(raw).hexdigest())


def _sync_value(v: object) -> str:
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    return '' if v is None else str(v)


def audit_pcb_sync(root_sch: Path, variant: Optional[str] = None) -> Tuple[Optional[Path], List[SyncIssue]]:
    """Compare schematic effective variant state with the PCB's serialized state.

    ``variant=None`` audits Default plus all named variants.  The audit is
    deliberately read-only and compares only properties KiCad's PCB variant
    model can represent safely: DNP, BOM/POS exclusion and fields.  Schematic
    exclude-from-board/simulation are reported separately when variant-specific.
    """
    root_sch = Path(root_sch).expanduser().resolve()
    board_path = find_board_file(root_sch)
    if board_path is None:
        return None, [SyncIssue('INFO', '', variant or '<All>', 'Board', '', '',
                                'No .kicad_pcb file was detected for this project.')]
    board = parse_board(board_path)
    rows, names = collect_matrix_rows(root_sch)
    if variant is None:
        checked = [DEFAULT_VARIANT] + list(names)
    else:
        checked = [_resolve_variant(variant, names, allow_default=True)]

    issues: List[SyncIssue] = []
    board_names_cf = {n.casefold(): n for n in board.variant_names}
    schema_names_cf = {n.casefold(): n for n in names}
    for v in checked:
        if v != DEFAULT_VARIANT and v.casefold() not in board_names_cf:
            issues.append(SyncIssue('ERROR', '', v, 'Variant metadata', 'present', 'missing',
                                    'Named variant is missing from PCB metadata. Run Update PCB from Schematic.'))
    if variant is None:
        for bname in board.variant_names:
            if bname.casefold() not in schema_names_cf:
                issues.append(SyncIssue('WARNING', '', bname, 'Variant metadata', 'missing', 'present',
                                        'PCB contains a variant that is not present in the schematic/project metadata.'))
        meta_cf={n.casefold() for n in board.variant_names}
        for bname in board.serialized_variant_names:
            if bname.casefold() not in meta_cf:
                issues.append(SyncIssue('WARNING', '', bname, 'Variant metadata', 'missing at board level', 'footprint blocks present',
                                        'Footprint variant blocks exist without matching board-level variant metadata.'))

    schema_by_ref: Dict[str, List[MatrixRow]] = {}
    for row in rows:
        ref = (row.reference or '').strip()
        if row.kind != 'symbol' or not ref or ref.startswith('#'):
            continue
        schema_by_ref.setdefault(ref, []).append(row)
    pcb_by_ref: Dict[str, List[PcbFootprintInfo]] = {}
    for fp in board.footprints:
        ref = (fp.reference or '').strip()
        if ref:
            pcb_by_ref.setdefault(ref, []).append(fp)

    for ref, rlist in sorted(schema_by_ref.items(), key=lambda kv: _natural_ref_key(kv[0])):
        if len(rlist) != 1:
            issues.append(SyncIssue('ERROR', ref, '', 'Reference', str(len(rlist)), '',
                                    'Reference is not unique across schematic instances; PCB sync cannot be audited safely by reference.'))
            continue
        row = rlist[0]
        flist = pcb_by_ref.get(ref, [])
        expects_board = any(not row.states[v].excluded_from_board for v in checked)
        if len(flist) == 0:
            if expects_board:
                issues.append(SyncIssue('ERROR', ref, ', '.join(checked), 'Footprint presence', 'present', 'missing',
                                        'Schematic expects this component on the board, but no matching PCB footprint was found.'))
            continue
        if len(flist) > 1:
            issues.append(SyncIssue('ERROR', ref, '', 'Reference', 'unique', str(len(flist)),
                                    'PCB contains duplicate footprints with this reference; sync cannot be audited safely.'))
            continue
        fp = flist[0]
        for v in checked:
            sch = row.states[v]
            pcb = fp.base if v == DEFAULT_VARIANT else fp.variants.get(v, fp.base)

            # The current PCB variant serialization has no exclude-from-board
            # or exclude-from-simulation override, so expose those as explicit
            # model limitations rather than pretending they are synchronized.
            if v != DEFAULT_VARIANT:
                base = row.states[DEFAULT_VARIANT]
                if sch.excluded_from_board != base.excluded_from_board:
                    issues.append(SyncIssue('WARNING', ref, v, 'Exclude from board', _sync_value(sch.excluded_from_board), 'not representable',
                                            'This schematic property changes by variant, but the audited PCB variant state has no equivalent per-variant property.'))
                if sch.exclude_from_sim != base.exclude_from_sim:
                    issues.append(SyncIssue('INFO', ref, v, 'Exclude from simulation', _sync_value(sch.exclude_from_sim), 'N/A',
                                            'Simulation exclusion is schematic-only and is not expected on the PCB.'))
            if sch.excluded_from_board:
                # There is no meaningful assembly-state comparison for a symbol
                # that this schematic configuration says is not on the board.
                continue

            for prop, sval, pval in (
                ('DNP', sch.dnp, pcb.dnp),
                ('Exclude from BOM', sch.excluded_from_bom, pcb.excluded_from_bom),
                ('Exclude from position files', sch.excluded_from_pos, pcb.excluded_from_pos),
            ):
                if sval != pval:
                    issues.append(SyncIssue('ERROR', ref, v, prop, _sync_value(sval), _sync_value(pval),
                                            'PCB assembly state differs from the schematic effective variant state.'))

            # Always compare core fields, plus fields that are variant-specific
            # on either side.  This avoids noisy warnings for static schematic
            # metadata that a board intentionally does not carry.
            field_names = {'Value', 'Footprint'}
            sbase = row.states[DEFAULT_VARIANT]
            pbase = fp.base
            for fname in set(sch.fields) | set(pcb.fields):
                if sch.fields.get(fname, '') != sbase.fields.get(fname, '') or pcb.fields.get(fname, '') != pbase.fields.get(fname, ''):
                    field_names.add(fname)
            for fname in ('Manufacturer', 'MPN'):
                if fname in sch.fields or fname in pcb.fields:
                    field_names.add(fname)
            field_names.discard('Reference')
            for fname in sorted(field_names, key=str.casefold):
                sval = sch.fields.get(fname, '')
                pval = pcb.fields.get(fname, '')
                if sval != pval:
                    sev = 'ERROR' if fname in {'Value', 'Footprint'} else 'WARNING'
                    issues.append(SyncIssue(sev, ref, v, fname, sval, pval,
                                            'PCB field differs from the schematic effective variant field.'))

    for ref, flist in sorted(pcb_by_ref.items(), key=lambda kv: _natural_ref_key(kv[0])):
        if ref not in schema_by_ref:
            issues.append(SyncIssue('INFO', ref, '', 'Footprint presence', 'missing', 'present',
                                    'PCB-only footprint/reference is not represented by a schematic symbol.'))

    return board_path, issues


def sync_summary(issues: Sequence[SyncIssue]) -> Tuple[str, int, int, int]:
    e = sum(1 for x in issues if x.severity == 'ERROR')
    w = sum(1 for x in issues if x.severity == 'WARNING')
    i = sum(1 for x in issues if x.severity == 'INFO')
    return ('OUT OF SYNC' if e else ('REVIEW' if w else 'SYNCED')), e, w, i


@dataclasses.dataclass
class ReleaseTask:
    label: str
    command: List[str]
    outputs: List[Path]


@dataclasses.dataclass
class ReleasePlan:
    root_sch: Path
    board_file: Optional[Path]
    variant: str
    output_dir: Path
    cli: Path
    tasks: List[ReleaseTask]
    input_hashes: Dict[str, str]
    cli_version: str


def collect_matrix_rows(root_sch: Path) -> Tuple[List[MatrixRow], List[str]]:
    """Return one row per hierarchical symbol/sheet instance.

    References can repeat across reusable sheets, so the row key includes the
    physical schematic file, object UUID, and hierarchical instance path.
    """
    _, _, _, _, _, schematics, names = _project_context(root_sch)
    rows: List[MatrixRow] = []
    for sch in schematics:
        for obj in sch.objects:
            for inst in obj.instances:
                states = {DEFAULT_VARIANT: obj.base.clone()}
                for name in names:
                    states[name] = _effective_state(obj.base, inst.variants.get(name), sch.version)
                ref = inst.reference or obj.label or obj.uuid
                key = f'{sch.path.resolve()}|{obj.uuid}|{inst.path_id}'
                rows.append(MatrixRow(
                    key=key,
                    file=sch.path.name,
                    kind=obj.kind,
                    uuid=obj.uuid,
                    instance_path=inst.path_id,
                    reference=ref,
                    base=obj.base.clone(),
                    states=states,
                ))
    rows.sort(key=lambda r: (r.file.casefold(), _natural_ref_key(r.reference), r.instance_path.casefold()))
    return rows, names


def _natural_ref_key(ref: str) -> Tuple[str, int, str]:
    m = re.match(r'([^0-9]*)([0-9]+)(.*)$', ref or '')
    if not m:
        return ((ref or '').casefold(), -1, '')
    return (m.group(1).casefold(), int(m.group(2)), m.group(3).casefold())


def _apply_patch_to_state(st: State, patch: VariantPatch) -> State:
    out = st.clone()
    for name, value in patch.field_updates.items():
        out.fields[name] = value
    if patch.dnp is not None:
        out.dnp = patch.dnp
    if patch.exclude_from_sim is not None:
        out.exclude_from_sim = patch.exclude_from_sim
    if patch.excluded_from_bom is not None:
        out.excluded_from_bom = patch.excluded_from_bom
    if patch.excluded_from_board is not None:
        out.excluded_from_board = patch.excluded_from_board
    if patch.excluded_from_pos is not None:
        out.excluded_from_pos = patch.excluded_from_pos
    return out


def plan_patch_variants(root_sch: Path, patches: Sequence[VariantPatch], title: str = 'Edit variant matrix') -> VariantPlan:
    """Plan semantic edits to named variants while preserving all other states.

    This is the write engine used by the Matrix and Part Substitution tabs.  It
    deliberately does not edit ``<Default>``: changing the base is a rebase
    operation and belongs in the dedicated Merge / Set Default workflow.
    """
    if not patches:
        raise VariantPromoterError('No variant edits were supplied.')
    (
        root_sch, project_file, project_entries, project_data, project_hash,
        schematics, old_names,
    ) = _project_context(root_sch)
    names_by_cf = {n.casefold(): n for n in old_names}
    patch_map: Dict[Tuple[str, str, str, str], VariantPatch] = {}
    for p in patches:
        if _is_default_name(p.variant):
            raise VariantPromoterError(
                'Matrix/Substitution editing of <Default> is intentionally disabled. '
                'Use the Merge / Set Default tab so remaining variants are rebased safely.'
            )
        actual = names_by_cf.get((p.variant or '').casefold())
        if not actual:
            raise VariantPromoterError(f'Variant {p.variant!r} no longer exists.')
        k = (str(Path(p.file).expanduser().resolve()).casefold(), p.uuid, p.instance_path, actual.casefold())
        if k in patch_map:
            # Combine repeated edits to the same target deterministically.
            prev = patch_map[k]
            merged = dataclasses.replace(prev, field_updates=dict(prev.field_updates))
            merged.field_updates.update(p.field_updates)
            for attr in ('dnp','exclude_from_sim','excluded_from_bom','excluded_from_board','excluded_from_pos'):
                v = getattr(p, attr)
                if v is not None:
                    setattr(merged, attr, v)
            patch_map[k] = merged
        else:
            patch_map[k] = dataclasses.replace(p, variant=actual, field_updates=dict(p.field_updates))

    for sch in schematics:
        pnames = _project_names_in_sch(sch)
        if len(pnames) > 1:
            raise VariantPromoterError(
                f'{sch.path.name} contains instance data for multiple projects '
                f'({", ".join(sorted(pnames))}); refusing cross-project rewrite.'
            )

    planned: List[PlannedFile] = []
    changes: List[ChangeRecord] = []
    anchors_created: set[str] = set()
    matched: set[Tuple[str, str, str, str]] = set()

    for sch in schematics:
        edits: List[Edit] = []
        for obj in sch.objects:
            if not obj.instances:
                continue
            for inst in obj.instances:
                old_states = {DEFAULT_VARIANT: obj.base.clone()}
                for name in old_names:
                    old_states[name] = _effective_state(obj.base, inst.variants.get(name), sch.version)

                desired_states: Dict[str, State] = {n: old_states[n].clone() for n in old_names}
                for name in old_names:
                    k = (str(sch.path.resolve()).casefold(), obj.uuid, inst.path_id, name.casefold())
                    patch = patch_map.get(k)
                    if patch is not None:
                        matched.add(k)
                        before = desired_states[name]
                        after = _apply_patch_to_state(before, patch)
                        desired_states[name] = after
                        changes.extend(_state_change_records(
                            before, after,
                            file=sch.path.name,
                            item=inst.reference or obj.label or obj.uuid,
                            instance=inst.path_id,
                            category_prefix=f'{name} ',
                        ))

                # Rebuild all named blocks for this instance from the unchanged base.
                for old_name, vnode in inst.variants.items():
                    edits.append(Edit(vnode.start, vnode.end, '', f'remove old variant block {old_name}'))
                blocks: List[str] = []
                indent = _child_indent(sch.text, inst.path_node)
                eol = _eol(sch.text)
                for name in old_names:
                    desired = desired_states[name]
                    flags, fields = _state_diff(obj.base, desired, obj.kind)
                    if flags or fields or (project_file is None and name not in anchors_created):
                        blocks.append(_render_variant(name, obj.base, desired, obj.kind, sch.version, indent, eol))
                        anchors_created.add(name)
                if blocks:
                    pos = _closing_line_start(sch.text, inst.path_node)
                    edits.append(Edit(pos, pos, ''.join(b + eol for b in blocks), 'insert regenerated variant blocks'))

        if edits:
            new_text = _apply_edits(sch.text, edits)
            SExprParser(new_text).parse()
            fd, temp_path = tempfile.mkstemp(prefix='kvw-', suffix='.kicad_sch')
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

    missing = sorted(set(patch_map) - matched)
    if missing:
        example = missing[0]
        raise VariantPromoterError(
            'One or more edited rows no longer match the project (it may have been changed in KiCad). '
            f'First unmatched key: {example}. Reload the project and try again.'
        )
    if not changes:
        raise VariantPromoterError('The requested edits do not change any effective variant values or flags.')

    # Matrix edits do not alter variant metadata or names.
    for pf in planned:
        changes.append(ChangeRecord('File rewrite', pf.path.name, 'Targeted edits', str(len(pf.edits)),
                                    'Rewrite with timestamped backup', pf.path.name))
    summary = [
        f'Apply {len(changes)} reviewed semantic/file change record(s).',
        f'Edited named variants: {", ".join(sorted({p.variant for p in patch_map.values()}, key=str.casefold))}.',
        f'Files to rewrite: {len(planned)} schematic file(s).',
        'All non-edited variants and Default retain their previous effective states.',
        'Timestamped backups are created before the first write and input hashes are rechecked at Apply.',
    ]
    return VariantPlan(
        source_root=root_sch,
        project_file=project_file,
        operation='patch_variants',
        title=title,
        schematic_files=planned,
        project_old_sha256=None,
        project_new_text=None,
        variants_before=list(old_names),
        variants_after=list(old_names),
        summary=summary,
        changes=changes,
    )


def lint_project(root_sch: Path) -> List[LintIssue]:
    root, project_file, project_entries, project_data, _, schematics, names = _project_context(root_sch)
    issues: List[LintIssue] = []
    serialized: set[str] = set()
    if project_file is None:
        issues.append(LintIssue('INFO', 'NO_PROJECT_FILE', root.name,
                                'No .kicad_pro was found; variant names rely on schematic anchors only.', root.name))

    for sch in schematics:
        if sch.version < BOM_LOGIC_FIX_VERSION and sch.variant_names:
            issues.append(LintIssue(
                'WARNING', 'LEGACY_IN_BOM_SEMANTICS', sch.path.name,
                f'Schematic version {sch.version} predates the 2026-03-06 variant in_bom semantics correction. '
                'The workbench preserves the legacy meaning, but upgrading/resaving in KiCad is recommended.',
                sch.path.name,
            ))
        serialized.update(sch.variant_names)
        pnames = _project_names_in_sch(sch)
        if len(pnames) > 1:
            issues.append(LintIssue('ERROR', 'SHARED_MULTI_PROJECT_INSTANCES', sch.path.name,
                                    'Instance data belongs to multiple projects; write operations are intentionally blocked.', sch.path.name))

        for obj in sch.objects:
            for inst in obj.instances:
                ref = inst.reference or obj.label or obj.uuid
                for name in names:
                    st = _effective_state(obj.base, inst.variants.get(name), sch.version)
                    vnode = inst.variants.get(name)
                    if vnode is not None and st.signature() == obj.base.signature():
                        issues.append(LintIssue('INFO', 'REDUNDANT_OVERRIDE', ref,
                                                'Variant block is semantically identical to Default and can be cleaned.',
                                                sch.path.name, name))
                    if obj.kind == 'symbol' and not ref.startswith('#'):
                        value = st.fields.get('Value', '')
                        fp = st.fields.get('Footprint', '')
                        if not st.dnp and not st.excluded_from_board and not value.strip():
                            issues.append(LintIssue('WARNING', 'EMPTY_VALUE', ref,
                                                    'Fitted symbol has an empty Value field.', sch.path.name, name))
                        # Avoid warning on connector/net-tie style schematic-only items that intentionally have no footprint
                        # if they are explicitly excluded from the board.
                        if not st.dnp and not st.excluded_from_board and not fp.strip():
                            issues.append(LintIssue('INFO', 'EMPTY_FOOTPRINT', ref,
                                                    'Fitted/on-board symbol has no Footprint field.', sch.path.name, name))
                        if st.excluded_from_bom and not st.dnp:
                            issues.append(LintIssue('INFO', 'BOM_EXCLUDED_BUT_FITTED', ref,
                                                    'Component is fitted but excluded from the BOM. Confirm this is intentional.',
                                                    sch.path.name, name))
                        if st.excluded_from_pos and not st.dnp and not st.excluded_from_board:
                            issues.append(LintIssue('INFO', 'POS_EXCLUDED_BUT_FITTED', ref,
                                                    'Component is fitted/on-board but excluded from position files.',
                                                    sch.path.name, name))

                # Footprint changes between variants deserve an explicit manufacturing warning.
                fps = {v: _state_for(obj.base, inst, v, sch.version).fields.get('Footprint', '')
                       for v in [DEFAULT_VARIANT] + list(names)}
                if len(set(fps.values())) > 1:
                    changed = ', '.join(f'{k}={v or "<empty>"}' for k, v in fps.items())
                    issues.append(LintIssue('WARNING', 'FOOTPRINT_DIFFERS_BY_VARIANT', ref,
                                            'Footprint differs across variants; Update PCB from Schematic and verify geometry/pin compatibility. '
                                            + changed, sch.path.name))

    project_names = set(project_entries)
    for n in sorted(serialized - project_names, key=str.casefold):
        issues.append(LintIssue('WARNING', 'SCHEMATIC_VARIANT_NOT_IN_PROJECT', n,
                                'Variant exists in schematic instance data but is missing from .kicad_pro metadata.', variant=n))
    for n in sorted(project_names - serialized, key=str.casefold):
        issues.append(LintIssue('INFO', 'METADATA_ONLY_VARIANT', n,
                                'Variant exists only in project metadata and currently inherits Default everywhere.', variant=n))
    if not names:
        issues.append(LintIssue('INFO', 'NO_NAMED_VARIANTS', root.name,
                                'Project has no named variants yet.'))
    return issues


def health_summary(issues: Sequence[LintIssue]) -> Tuple[str, int, int, int]:
    e = sum(1 for x in issues if x.severity == 'ERROR')
    w = sum(1 for x in issues if x.severity == 'WARNING')
    i = sum(1 for x in issues if x.severity == 'INFO')
    status = 'BLOCKED' if e else ('REVIEW' if w else 'GOOD')
    return status, e, w, i


def find_board_file(root_sch: Path) -> Optional[Path]:
    root_sch = Path(root_sch).resolve()
    project = find_project_file(root_sch)
    candidates: List[Path] = []
    if project:
        exact = project.with_suffix('.kicad_pcb')
        if exact.exists():
            candidates.append(exact)
    direct = root_sch.with_suffix('.kicad_pcb')
    if direct.exists() and direct not in candidates:
        candidates.append(direct)
    if not candidates:
        candidates = sorted(root_sch.parent.glob('*.kicad_pcb'))
    return candidates[0].resolve() if len(candidates) == 1 else (candidates[0].resolve() if candidates else None)


def find_kicad_cli() -> Optional[Path]:
    hit = shutil.which('kicad-cli') or shutil.which('kicad-cli.exe')
    if hit:
        return Path(hit).resolve()
    candidates: List[Path] = []
    if os.name == 'nt':
        for envname in ('ProgramFiles', 'ProgramFiles(x86)'):
            base = os.environ.get(envname)
            if base:
                for ver in ('10.0', '11.0', '9.0'):
                    candidates.append(Path(base) / 'KiCad' / ver / 'bin' / 'kicad-cli.exe')
    else:
        candidates += [Path('/usr/bin/kicad-cli'), Path('/usr/local/bin/kicad-cli'), Path('/opt/homebrew/bin/kicad-cli')]
    return next((p.resolve() for p in candidates if p.exists()), None)


def build_release_plan(
    root_sch: Path,
    variant: str,
    output_dir: Path,
    *,
    cli_path: Optional[Path] = None,
    include_bom: bool = True,
    include_schematic_pdf: bool = True,
    include_gerbers: bool = True,
    include_drill: bool = True,
    include_pos: bool = True,
    include_board_pdf: bool = True,
    include_step: bool = False,
    include_erc: bool = True,
    include_drc: bool = True,
) -> ReleasePlan:
    root_sch = Path(root_sch).resolve()
    _, project_file, _, _, _, schematics, names = _project_context(root_sch)
    variant = _resolve_variant(variant, names, allow_default=True)
    cli = Path(cli_path).resolve() if cli_path else find_kicad_cli()
    if cli is None or not cli.exists():
        raise VariantPromoterError('kicad-cli was not found. Install KiCad or browse to kicad-cli.exe.')
    board = find_board_file(root_sch)
    output_dir = Path(output_dir).expanduser().resolve()
    variant_arg = [] if variant == DEFAULT_VARIANT else ['--variant', variant]
    tasks: List[ReleaseTask] = []

    if include_erc:
        out = output_dir / 'erc_report.rpt'
        tasks.append(ReleaseTask('ERC report', [str(cli), 'sch', 'erc', '--severity-all',
                                                '--output', str(out), str(root_sch)], [out]))
    if include_bom:
        out = output_dir / 'bom.csv'
        tasks.append(ReleaseTask('Schematic BOM', [str(cli), 'sch', 'export', 'bom', *variant_arg,
                                                   '--exclude-dnp', '--output', str(out), str(root_sch)], [out]))
    if include_schematic_pdf:
        out = output_dir / 'schematic.pdf'
        tasks.append(ReleaseTask('Schematic PDF', [str(cli), 'sch', 'export', 'pdf', *variant_arg,
                                                   '--output', str(out), str(root_sch)], [out]))

    if board:
        if include_drc:
            out = output_dir / 'drc_report.rpt'
            tasks.append(ReleaseTask('DRC + schematic parity report', [str(cli), 'pcb', 'drc', '--severity-all',
                                                                       '--schematic-parity', '--output', str(out), str(board)], [out]))
        if include_gerbers:
            outdir = output_dir / 'gerbers'
            tasks.append(ReleaseTask('Gerbers', [str(cli), 'pcb', 'export', 'gerbers', *variant_arg,
                                                '--board-plot-params', '--output', str(outdir), str(board)], [outdir]))
        if include_drill:
            outdir = output_dir / 'drill'
            tasks.append(ReleaseTask('Drill files', [str(cli), 'pcb', 'export', 'drill',
                                                     '--generate-map', '--generate-report', '--output', str(outdir), str(board)], [outdir]))
        if include_pos:
            out = output_dir / 'positions.csv'
            tasks.append(ReleaseTask('Position file', [str(cli), 'pcb', 'export', 'pos', *variant_arg,
                                                     '--exclude-dnp', '--format', 'csv', '--output', str(out), str(board)], [out]))
        if include_board_pdf:
            out = output_dir / 'assembly_fab.pdf'
            layers = 'F.Fab,B.Fab,F.Silkscreen,B.Silkscreen,Edge.Cuts'
            tasks.append(ReleaseTask('Assembly/Fab PDF', [str(cli), 'pcb', 'export', 'pdf', *variant_arg,
                                                  '--layers', layers, '--mode-multipage',
                                                  '--crossout-DNP-footprints-on-fab-layers',
                                                  '--output', str(out), str(board)], [out]))
        if include_step:
            out = output_dir / 'board.step'
            tasks.append(ReleaseTask('STEP', [str(cli), 'pcb', 'export', 'step', *variant_arg,
                                             '--no-dnp', '--output', str(out), str(board)], [out]))
    elif any((include_gerbers, include_drill, include_pos, include_board_pdf, include_step, include_drc)):
        # Schematic-only projects can still make a useful release.
        pass

    if not tasks:
        raise VariantPromoterError('No release outputs were selected.')

    # Snapshot every design input used by the release preview.  This prevents a
    # user from previewing one configuration, changing the project in KiCad,
    # then accidentally generating a release from a different on-disk state.
    input_paths: List[Path] = [sch.path.resolve() for sch in schematics]
    if project_file is not None:
        input_paths.append(project_file.resolve())
    if board is not None:
        input_paths.append(board.resolve())
    input_hashes = {str(path): _hash_file(path) for path in dict.fromkeys(input_paths)}

    cli_version = 'unknown'
    try:
        cp = subprocess.run([str(cli), 'version'], capture_output=True, text=True, timeout=10)
        version_text = (cp.stdout or cp.stderr).strip()
        if cp.returncode == 0 and version_text:
            cli_version = version_text.splitlines()[0].strip()
    except Exception:
        pass

    return ReleasePlan(root_sch, board, variant, output_dir, cli, tasks, input_hashes, cli_version)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run_release_plan(plan: ReleasePlan, *, zip_release: bool = True, progress_cb=None) -> Tuple[Path, List[str]]:
    # Revalidate the exact files that were used to build the preview.  Release
    # generation is read-only with respect to the project, but stale previews
    # are still dangerous in a production workflow.
    for raw_path, expected in plan.input_hashes.items():
        path = Path(raw_path)
        if not path.exists():
            raise VariantPromoterError(f'Release input disappeared since preview: {path.name}. Preview again.')
        if _hash_file(path) != expected:
            raise VariantPromoterError(f'{path.name} changed since the release preview. Preview the release again before generating it.')

    plan.output_dir.mkdir(parents=True, exist_ok=True)
    log: List[str] = []
    total_tasks = len(plan.tasks)
    for task_index, task in enumerate(plan.tasks, start=1):
        if progress_cb:
            progress_cb(task_index - 1, total_tasks, task.label)
        for out in task.outputs:
            if out.suffix == '' and not out.exists():
                out.mkdir(parents=True, exist_ok=True)
        log.append('$ ' + subprocess.list2cmdline(task.command))
        cp = subprocess.run(task.command, cwd=str(plan.root_sch.parent), capture_output=True, text=True)
        if cp.stdout.strip():
            log.append(cp.stdout.rstrip())
        if cp.stderr.strip():
            log.append(cp.stderr.rstrip())
        if cp.returncode != 0:
            raise VariantPromoterError(f'{task.label} failed with exit code {cp.returncode}.\n' + '\n'.join(log[-4:]))
        if progress_cb:
            progress_cb(task_index, total_tasks, task.label)

    files: List[dict] = []
    for p in sorted(plan.output_dir.rglob('*')):
        if p.is_file() and p.name not in {'variant_manifest.json'} and not p.name.endswith('.zip'):
            files.append({
                'path': str(p.relative_to(plan.output_dir)).replace('\\', '/'),
                'size': p.stat().st_size,
                'sha256': _hash_file(p),
            })
    manifest = {
        'schema': 'kicad-variant-workbench-release-1',
        'generated_utc': _dt.datetime.now(_dt.timezone.utc).isoformat(),
        'workbench_version': APP_VERSION,
        'variant': plan.variant,
        'root_schematic': plan.root_sch.name,
        'board': plan.board_file.name if plan.board_file else None,
        'kicad_cli': str(plan.cli),
        'kicad_cli_version': plan.cli_version,
        'inputs': [
            {
                'path': (str(Path(path).resolve().relative_to(plan.root_sch.parent))
                         if Path(path).resolve().is_relative_to(plan.root_sch.parent)
                         else str(Path(path).resolve())),
                'sha256': digest,
            }
            for path, digest in sorted(plan.input_hashes.items())
        ],
        'commands': [t.command for t in plan.tasks],
        'files': files,
    }
    manifest_path = plan.output_dir / 'variant_manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    if zip_release:
        zip_path = plan.output_dir.with_suffix('.zip')
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(plan.output_dir.rglob('*')):
                if p.is_file():
                    zf.write(p, p.relative_to(plan.output_dir))
        log.append(f'Created {zip_path}')
    return manifest_path, log


def format_state_compact(st: State, base: Optional[State] = None) -> str:
    bits: List[str] = []
    bits.append('DNP' if st.dnp else 'FIT')
    if st.excluded_from_bom:
        bits.append('noBOM')
    if st.excluded_from_pos:
        bits.append('noPOS')
    if st.excluded_from_board:
        bits.append('noPCB')
    val = st.fields.get('Value', '')
    if val:
        bits.append(val)
    if base is not None and st.signature() == base.signature():
        bits.append('=Default')
    return ' · '.join(bits)

# ---------- guided GUI ----------

def run_gui_legacy(initial: Optional[str] = None, plugin_mode: bool = False, launch_note: str = '') -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as e:
        print(f'Tkinter is unavailable: {e}', file=sys.stderr)
        return 2

    OPERATIONS = [
        'Set variant as Default',
        'Swap variant with Default',
        'Rename variant',
        'Duplicate / create variant',
        'Delete variant',
        'Compare two variants',
        'Clean redundant overrides',
    ]

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f'{APP_NAME} {APP_VERSION}')
            self.geometry('1180x760')
            self.minsize(920, 620)
            self.analysis: Optional[ProjectAnalysis] = None
            self.plan: Optional[VariantPlan] = None
            self.records: List[ChangeRecord] = []
            self.current_step = 0
            self.plugin_mode = plugin_mode

            self.path_var = tk.StringVar(value=initial or '')
            self.status_var = tk.StringVar(value='Step 1 — choose a KiCad schematic project.')
            self.op_var = tk.StringVar(value=OPERATIONS[0])
            self.source_var = tk.StringVar()
            self.target_var = tk.StringVar()
            self.compare_var = tk.StringVar(value=DEFAULT_VARIANT)
            self.keep_var = tk.BooleanVar(value=False)
            self.confirm_closed_var = tk.BooleanVar(value=False)
            self.filter_var = tk.StringVar()

            root = ttk.Frame(self, padding=12)
            root.pack(fill='both', expand=True)
            root.columnconfigure(1, weight=1)
            root.rowconfigure(1, weight=1)

            header = ttk.Frame(root)
            header.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 10))
            ttk.Label(header, text='KiCad Design Variant Manager', font=('TkDefaultFont', 15, 'bold')).pack(side='left')
            ttk.Label(header, text=f'v{APP_VERSION}').pack(side='left', padx=(8, 0))
            if plugin_mode:
                ttk.Label(header, text='• KiCad IPC plugin').pack(side='left', padx=(12, 0))

            rail = ttk.Frame(root, padding=(0, 8, 16, 8))
            rail.grid(row=1, column=0, sticky='nsw')
            self.step_labels: List[ttk.Label] = []
            for i, text in enumerate(['1  Project', '2  Operation', '3  Review', '4  Apply / finish']):
                lab = ttk.Label(rail, text=text, width=20, padding=(6, 9))
                lab.pack(anchor='w', fill='x')
                self.step_labels.append(lab)

            body = ttk.Frame(root)
            body.grid(row=1, column=1, sticky='nsew')
            body.rowconfigure(0, weight=1)
            body.columnconfigure(0, weight=1)
            self.pages: List[ttk.Frame] = []
            for _ in range(4):
                f = ttk.Frame(body, padding=4)
                f.grid(row=0, column=0, sticky='nsew')
                self.pages.append(f)

            self._build_project_page(self.pages[0])
            self._build_operation_page(self.pages[1])
            self._build_review_page(self.pages[2])
            self._build_apply_page(self.pages[3])

            footer = ttk.Frame(root)
            footer.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(10, 0))
            footer.columnconfigure(1, weight=1)
            self.back_btn = ttk.Button(footer, text='← Back', command=self.back)
            self.back_btn.grid(row=0, column=0)
            ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=1, sticky='w', padx=12)
            self.next_btn = ttk.Button(footer, text='Next →', command=self.next)
            self.next_btn.grid(row=0, column=2)
            ttk.Button(footer, text='Close', command=self.destroy).grid(row=0, column=3, padx=(8, 0))

            self.filter_var.trace_add('write', lambda *_: self._refresh_record_tree())
            self.op_var.trace_add('write', lambda *_: self._update_operation_controls())
            self.source_var.trace_add('write', lambda *_: self._invalidate_plan())
            self.target_var.trace_add('write', lambda *_: self._invalidate_plan())
            self.compare_var.trace_add('write', lambda *_: self._invalidate_plan())
            self.keep_var.trace_add('write', lambda *_: self._invalidate_plan())

            self.show_step(0)
            if initial:
                self.after(80, self.load_project)
            elif launch_note:
                self.project_message_var.set(launch_note)

        # ----- page construction -----
        def _build_project_page(self, page: ttk.Frame) -> None:
            page.columnconfigure(0, weight=1)
            page.rowconfigure(5, weight=1)
            ttk.Label(page, text='Step 1 — Select project', font=('TkDefaultFont', 12, 'bold')).grid(row=0, column=0, sticky='w')
            ttk.Label(
                page,
                text='Choose any top-level .kicad_sch in the project. Flat multi-root projects and ordinary hierarchies are discovered automatically.',
                wraplength=860,
            ).grid(row=1, column=0, sticky='ew', pady=(4, 12))

            pick = ttk.Frame(page)
            pick.grid(row=2, column=0, sticky='ew')
            pick.columnconfigure(0, weight=1)
            ttk.Entry(pick, textvariable=self.path_var).grid(row=0, column=0, sticky='ew')
            ttk.Button(pick, text='Browse…', command=self.browse).grid(row=0, column=1, padx=(8, 0))
            ttk.Button(pick, text='Load / refresh', command=self.load_project).grid(row=0, column=2, padx=(8, 0))

            self.project_message_var = tk.StringVar(value=launch_note or 'No project loaded yet.')
            ttk.Label(page, textvariable=self.project_message_var, wraplength=900).grid(row=3, column=0, sticky='ew', pady=(10, 8))

            self.project_cards = ttk.Frame(page)
            self.project_cards.grid(row=4, column=0, sticky='ew', pady=(0, 8))
            self.card_vars = [tk.StringVar(value='—') for _ in range(4)]
            titles = ['Schematics', 'Symbol instances', 'Variants', 'Project file']
            for i, (title, var) in enumerate(zip(titles, self.card_vars)):
                box = ttk.LabelFrame(self.project_cards, text=title, padding=8)
                box.grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else 6, 0))
                self.project_cards.columnconfigure(i, weight=1)
                ttk.Label(box, textvariable=var).pack(anchor='w')

            table_box = ttk.LabelFrame(page, text='Variant overview vs Default', padding=6)
            table_box.grid(row=5, column=0, sticky='nsew')
            table_box.rowconfigure(0, weight=1)
            table_box.columnconfigure(0, weight=1)
            cols = ('diff', 'dnp', 'bom', 'value', 'footprint', 'fields', 'flags')
            self.stats_tree = ttk.Treeview(table_box, columns=cols, show='tree headings', selectmode='browse')
            self.stats_tree.heading('#0', text='Variant')
            self.stats_tree.column('#0', width=180, stretch=True)
            headings = {
                'diff': 'Changed items', 'dnp': 'DNP', 'bom': 'BOM excluded', 'value': 'Value Δ',
                'footprint': 'Footprint Δ', 'fields': 'Field Δ', 'flags': 'Flag Δ'
            }
            for c in cols:
                self.stats_tree.heading(c, text=headings[c])
                self.stats_tree.column(c, width=95, anchor='center')
            self.stats_tree.grid(row=0, column=0, sticky='nsew')
            sb = ttk.Scrollbar(table_box, orient='vertical', command=self.stats_tree.yview)
            sb.grid(row=0, column=1, sticky='ns')
            self.stats_tree.configure(yscrollcommand=sb.set)

        def _build_operation_page(self, page: ttk.Frame) -> None:
            page.columnconfigure(1, weight=1)
            ttk.Label(page, text='Step 2 — Choose variant operation', font=('TkDefaultFont', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
            ttk.Label(page, text='Operation:').grid(row=1, column=0, sticky='w', pady=(14, 5))
            self.op_combo = ttk.Combobox(page, textvariable=self.op_var, values=OPERATIONS, state='readonly', width=34)
            self.op_combo.grid(row=1, column=1, sticky='w', pady=(14, 5))

            ttk.Label(page, text='Source variant:').grid(row=2, column=0, sticky='w', pady=5)
            self.source_combo = ttk.Combobox(page, textvariable=self.source_var, state='readonly', width=34)
            self.source_combo.grid(row=2, column=1, sticky='w', pady=5)

            self.target_label = ttk.Label(page, text='New name:')
            self.target_label.grid(row=3, column=0, sticky='w', pady=5)
            self.target_entry = ttk.Entry(page, textvariable=self.target_var, width=38)
            self.target_entry.grid(row=3, column=1, sticky='w', pady=5)

            self.compare_label = ttk.Label(page, text='Compare against:')
            self.compare_label.grid(row=4, column=0, sticky='w', pady=5)
            self.compare_combo = ttk.Combobox(page, textvariable=self.compare_var, state='readonly', width=34)
            self.compare_combo.grid(row=4, column=1, sticky='w', pady=5)

            self.keep_check = ttk.Checkbutton(
                page, text='Keep the promoted source as an equivalent named variant', variable=self.keep_var
            )
            self.keep_check.grid(row=5, column=1, sticky='w', pady=5)

            self.op_help_var = tk.StringVar()
            help_box = ttk.LabelFrame(page, text='What this will do', padding=12)
            help_box.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(18, 8))
            ttk.Label(help_box, textvariable=self.op_help_var, wraplength=850, justify='left').pack(anchor='w')

            safety = ttk.LabelFrame(page, text='Safety model', padding=12)
            safety.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(8, 0))
            ttk.Label(
                safety,
                text=(
                    'Every write operation is previewed first. The manager snapshots effective variant states, '
                    'rechecks source-file hashes immediately before Apply, writes timestamped backups, uses atomic replacement, '
                    'and refuses a hierarchy when one serialized Default cannot represent the selected variant.'
                ),
                wraplength=850,
            ).pack(anchor='w')

        def _build_review_page(self, page: ttk.Frame) -> None:
            page.columnconfigure(0, weight=1)
            page.rowconfigure(4, weight=1)
            ttk.Label(page, text='Step 3 — Review', font=('TkDefaultFont', 12, 'bold')).grid(row=0, column=0, sticky='w')
            self.review_title_var = tk.StringVar(value='Generate a preview from Step 2.')
            ttk.Label(page, textvariable=self.review_title_var, wraplength=900).grid(row=1, column=0, sticky='ew', pady=(4, 8))

            summary_box = ttk.LabelFrame(page, text='Preview summary', padding=8)
            summary_box.grid(row=2, column=0, sticky='ew')
            self.review_summary_var = tk.StringVar(value='—')
            ttk.Label(summary_box, textvariable=self.review_summary_var, wraplength=900, justify='left').pack(anchor='w')

            toolbar = ttk.Frame(page)
            toolbar.grid(row=3, column=0, sticky='ew', pady=(8, 5))
            ttk.Label(toolbar, text='Filter:').pack(side='left')
            ttk.Entry(toolbar, textvariable=self.filter_var, width=30).pack(side='left', padx=(5, 10))
            ttk.Button(toolbar, text='Export CSV…', command=self.export_csv).pack(side='left')
            self.record_count_var = tk.StringVar(value='0 records')
            ttk.Label(toolbar, textvariable=self.record_count_var).pack(side='right')

            box = ttk.Frame(page)
            box.grid(row=4, column=0, sticky='nsew')
            box.rowconfigure(0, weight=1)
            box.columnconfigure(0, weight=1)
            cols = ('category', 'item', 'property', 'before', 'after', 'file')
            self.change_tree = ttk.Treeview(box, columns=cols, show='headings')
            widths = {'category': 115, 'item': 120, 'property': 170, 'before': 220, 'after': 220, 'file': 145}
            for c in cols:
                self.change_tree.heading(c, text=c.title())
                self.change_tree.column(c, width=widths[c], stretch=(c in {'before', 'after'}))
            self.change_tree.grid(row=0, column=0, sticky='nsew')
            y = ttk.Scrollbar(box, orient='vertical', command=self.change_tree.yview)
            y.grid(row=0, column=1, sticky='ns')
            x = ttk.Scrollbar(box, orient='horizontal', command=self.change_tree.xview)
            x.grid(row=1, column=0, sticky='ew')
            self.change_tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)

        def _build_apply_page(self, page: ttk.Frame) -> None:
            page.columnconfigure(0, weight=1)
            ttk.Label(page, text='Step 4 — Apply / finish', font=('TkDefaultFont', 12, 'bold')).grid(row=0, column=0, sticky='w')
            self.apply_intro_var = tk.StringVar(value='Review the plan first.')
            ttk.Label(page, textvariable=self.apply_intro_var, wraplength=900, justify='left').grid(row=1, column=0, sticky='ew', pady=(6, 12))

            warn_box = ttk.LabelFrame(page, text='Before writing', padding=12)
            warn_box.grid(row=2, column=0, sticky='ew')
            close_text = (
                'I have SAVED and CLOSED all KiCad editors that have this project open. '
                'This prevents KiCad from later overwriting the schematic/project metadata from an in-memory copy.'
            )
            ttk.Checkbutton(warn_box, text=close_text, variable=self.confirm_closed_var, command=self._update_apply_button).pack(anchor='w')
            if plugin_mode:
                ttk.Label(
                    warn_box,
                    text='Plugin note: this window is a separate process. After launching it from PCB Editor, save the project and close KiCad before pressing Apply.',
                    wraplength=850,
                ).pack(anchor='w', pady=(8, 0))

            controls = ttk.Frame(page)
            controls.grid(row=3, column=0, sticky='ew', pady=(14, 8))
            self.apply_btn = ttk.Button(controls, text='Apply changes', command=self.apply_changes, state='disabled')
            self.apply_btn.pack(side='left')
            self.progress = ttk.Progressbar(controls, mode='determinate', maximum=100, length=260)
            self.progress.pack(side='left', padx=(12, 0))

            result_box = ttk.LabelFrame(page, text='Result / next actions', padding=10)
            result_box.grid(row=4, column=0, sticky='nsew', pady=(8, 0))
            page.rowconfigure(4, weight=1)
            self.result_text = tk.Text(result_box, wrap='word', height=14)
            self.result_text.pack(fill='both', expand=True)
            self.result_text.insert('end', 'Nothing has been written yet.\n')
            self.result_text.configure(state='disabled')

        # ----- navigation / state -----
        def show_step(self, step: int) -> None:
            self.current_step = max(0, min(3, step))
            self.pages[self.current_step].tkraise()
            for i, lab in enumerate(self.step_labels):
                prefix = '▶ ' if i == self.current_step else ('✓ ' if i < self.current_step else '  ')
                lab.configure(text=prefix + ['1  Project', '2  Operation', '3  Review', '4  Apply / finish'][i])
            self.back_btn.configure(state='normal' if self.current_step > 0 else 'disabled')
            if self.current_step == 3:
                self.next_btn.configure(state='disabled', text='Next →')
            else:
                self.next_btn.configure(state='normal', text='Next →')

        def back(self) -> None:
            self.show_step(self.current_step - 1)

        def next(self) -> None:
            if self.current_step == 0:
                if not self.analysis:
                    self.load_project()
                if self.analysis:
                    self.show_step(1)
            elif self.current_step == 1:
                if self.generate_preview():
                    self.show_step(2)
            elif self.current_step == 2:
                if self.op_var.get() == 'Compare two variants':
                    self.apply_intro_var.set('Comparison complete. No files will be changed. You can export the comparison CSV or go Back to choose another operation.')
                    self.confirm_closed_var.set(False)
                    self.apply_btn.configure(state='disabled')
                else:
                    self.apply_intro_var.set(
                        (self.plan.title + '.\n\n' if self.plan else '') +
                        'The preview is ready. Confirm that KiCad has released the project files, then apply the exact reviewed plan.'
                    )
                    self.confirm_closed_var.set(False)
                    self._update_apply_button()
                self.show_step(3)

        def _invalidate_plan(self) -> None:
            self.plan = None
            self.records = []
            self.confirm_closed_var.set(False)
            if hasattr(self, 'apply_btn'):
                self.apply_btn.configure(state='disabled')

        # ----- project load -----
        def browse(self) -> None:
            p = filedialog.askopenfilename(
                title='Choose KiCad schematic',
                filetypes=[('KiCad schematic', '*.kicad_sch'), ('All files', '*.*')],
            )
            if p:
                self.path_var.set(p)
                self.load_project()

        def load_project(self) -> None:
            self._invalidate_plan()
            try:
                p = Path(self.path_var.get()).expanduser().resolve()
                self.analysis = analyze_project(p)
                a = self.analysis
                self.path_var.set(str(a.root))
                self.project_message_var.set(
                    f'✓ Loaded {a.root.name}. ' +
                    (f'Project metadata: {a.project_file.name}.' if a.project_file else 'No .kicad_pro metadata found.') +
                    (('  ⚠ ' + ' '.join(a.warnings)) if a.warnings else '')
                )
                self.card_vars[0].set(str(a.schematic_count))
                self.card_vars[1].set(str(a.symbol_instances))
                self.card_vars[2].set(str(len(a.variant_names)))
                self.card_vars[3].set(a.project_file.name if a.project_file else 'not found')
                for iid in self.stats_tree.get_children():
                    self.stats_tree.delete(iid)
                for st in a.stats:
                    self.stats_tree.insert('', 'end', text=st.name, values=(
                        st.differing_instances, st.dnp_instances, st.bom_excluded_instances,
                        st.value_differences, st.footprint_differences, st.field_differences, st.flag_differences,
                    ))
                named = list(a.variant_names)
                self.source_combo['values'] = named
                self.compare_combo['values'] = [DEFAULT_VARIANT] + named
                if named:
                    if self.source_var.get() not in named:
                        self.source_var.set(named[0])
                else:
                    self.source_var.set('')
                self.compare_var.set(DEFAULT_VARIANT)
                self._update_operation_controls()
                self.status_var.set(f'✓ Project loaded — {len(named)} named variant(s).')
            except Exception as e:
                self.analysis = None
                self.project_message_var.set(f'✗ {e}')
                self.status_var.set('✗ Project could not be loaded.')
                messagebox.showerror(APP_NAME, str(e), parent=self)

        # ----- operation controls / preview -----
        def _update_operation_controls(self) -> None:
            if not hasattr(self, 'source_combo'):
                return
            op = self.op_var.get()
            named = list(self.analysis.variant_names) if self.analysis else []
            allow_default_source = op in {'Duplicate / create variant', 'Compare two variants'}
            source_values = ([DEFAULT_VARIANT] if allow_default_source else []) + named
            self.source_combo['values'] = source_values
            if source_values and self.source_var.get() not in source_values:
                self.source_var.set(source_values[0])

            needs_target = op in {'Swap variant with Default', 'Rename variant', 'Duplicate / create variant'}
            target_text = {
                'Swap variant with Default': 'Name for old Default:',
                'Rename variant': 'New variant name:',
                'Duplicate / create variant': 'New variant name:',
            }.get(op, 'New name:')
            self.target_label.configure(text=target_text)
            self.target_label.grid() if needs_target else self.target_label.grid_remove()
            self.target_entry.grid() if needs_target else self.target_entry.grid_remove()

            is_compare = op == 'Compare two variants'
            self.compare_label.grid() if is_compare else self.compare_label.grid_remove()
            self.compare_combo.grid() if is_compare else self.compare_combo.grid_remove()
            is_promote = op == 'Set variant as Default'
            self.keep_check.grid() if is_promote else self.keep_check.grid_remove()

            help_text = {
                'Set variant as Default': 'Promotes the selected variant into the base schematic. Every other named variant is rebased so it still means exactly what it meant before.',
                'Swap variant with Default': 'Promotes the selected variant, but also creates a named variant containing the previous Default. This is the safest way to change which configuration is considered baseline.',
                'Rename variant': 'Renames a variant everywhere in the schematic instance data and .kicad_pro metadata, preserving its effective values and flags.',
                'Duplicate / create variant': 'Creates an exact clone of any named variant or of <Default>. Use <Default> to create a clean new variant baseline.',
                'Delete variant': 'Removes one named variant while leaving Default and every other variant unchanged.',
                'Compare two variants': 'Read-only comparison of fields, footprints, values, DNP/BOM/position/simulation/board flags across every symbol/sheet instance.',
                'Clean redundant overrides': 'Regenerates variant blocks from their effective states, eliminating overrides that merely repeat Default. No variant behavior is intentionally changed.',
            }.get(op, '')
            self.op_help_var.set(help_text)
            self._invalidate_plan()

        def generate_preview(self) -> bool:
            if not self.analysis:
                messagebox.showerror(APP_NAME, 'Load a project first.', parent=self)
                return False
            root = self.analysis.root
            op = self.op_var.get()
            try:
                self.plan = None
                if op == 'Set variant as Default':
                    self.plan = plan_promote_variant(root, self.source_var.get(), self.keep_var.get())
                    self.records = list(self.plan.changes)
                elif op == 'Swap variant with Default':
                    self.plan = plan_swap_default(root, self.source_var.get(), self.target_var.get())
                    self.records = list(self.plan.changes)
                elif op == 'Rename variant':
                    self.plan = plan_rename_variant(root, self.source_var.get(), self.target_var.get())
                    self.records = list(self.plan.changes)
                elif op == 'Duplicate / create variant':
                    self.plan = plan_duplicate_variant(root, self.source_var.get(), self.target_var.get())
                    self.records = list(self.plan.changes)
                elif op == 'Delete variant':
                    self.plan = plan_delete_variant(root, self.source_var.get())
                    self.records = list(self.plan.changes)
                elif op == 'Compare two variants':
                    left = self.source_var.get()
                    right = self.compare_var.get()
                    self.records = compare_variants(root, left, right)
                    self.review_title_var.set(f'Compare {left} → {right}')
                    self.review_summary_var.set(
                        f'Read-only comparison. {len(self.records)} differing properties across the full project hierarchy. No files are scheduled for writing.'
                    )
                elif op == 'Clean redundant overrides':
                    self.plan = plan_clean_overrides(root)
                    self.records = list(self.plan.changes)
                else:
                    raise VariantPromoterError('Unknown operation.')

                if self.plan:
                    self.review_title_var.set(self.plan.title)
                    self.review_summary_var.set('\n'.join('• ' + s for s in self.plan.summary))
                self.filter_var.set('')
                self._refresh_record_tree()
                self.status_var.set(f'✓ Preview ready — {len(self.records)} visible change record(s).')
                return True
            except Exception as e:
                self.plan = None
                self.records = []
                self._refresh_record_tree()
                self.status_var.set('✗ Preview failed.')
                messagebox.showerror(APP_NAME, str(e), parent=self)
                return False

        def _refresh_record_tree(self) -> None:
            if not hasattr(self, 'change_tree'):
                return
            for iid in self.change_tree.get_children():
                self.change_tree.delete(iid)
            needle = self.filter_var.get().strip().casefold()
            shown = 0
            for r in self.records:
                hay = ' '.join([r.category, r.item, r.property, r.before, r.after, r.file, r.instance]).casefold()
                if needle and needle not in hay:
                    continue
                self.change_tree.insert('', 'end', values=(r.category, r.item, r.property, r.before, r.after, r.file))
                shown += 1
            self.record_count_var.set(f'{shown} shown / {len(self.records)} total')

        def export_csv(self) -> None:
            if not self.records:
                messagebox.showinfo(APP_NAME, 'There are no comparison/change records to export.', parent=self)
                return
            path = filedialog.asksaveasfilename(
                title='Export variant comparison/change preview',
                defaultextension='.csv',
                filetypes=[('CSV', '*.csv')],
                initialfile='variant_changes.csv',
            )
            if path:
                try:
                    export_changes_csv(self.records, Path(path))
                    self.status_var.set(f'✓ Exported {len(self.records)} records to {Path(path).name}.')
                except Exception as e:
                    messagebox.showerror(APP_NAME, str(e), parent=self)

        # ----- apply -----
        def _update_apply_button(self) -> None:
            can = bool(self.plan and self.confirm_closed_var.get())
            self.apply_btn.configure(state='normal' if can else 'disabled')

        def _set_result(self, text: str) -> None:
            self.result_text.configure(state='normal')
            self.result_text.delete('1.0', 'end')
            self.result_text.insert('end', text)
            self.result_text.configure(state='disabled')

        def apply_changes(self) -> None:
            if not self.plan:
                return
            if not self.confirm_closed_var.get():
                messagebox.showwarning(APP_NAME, 'Confirm that KiCad has released the project before applying.', parent=self)
                return
            if not messagebox.askyesno(
                APP_NAME,
                f'Apply this reviewed operation?\n\n{self.plan.title}\n\nTimestamped backups will be created first.',
                parent=self,
            ):
                return
            try:
                self.progress['value'] = 10
                self.update_idletasks()
                backups = apply_plan(self.plan)
                self.progress['value'] = 100
                text = '✓ Operation completed successfully.\n\nBackups created:\n'
                if backups:
                    text += ''.join(f'  • {b}\n' for b in backups)
                else:
                    text += '  • No file contents changed; no backups were required.\n'
                text += (
                    '\nNext:\n'
                    '  1. Reopen KiCad and verify the variant list and <Default>.\n'
                    '  2. For Default-changing operations, run Update PCB from Schematic before manufacturing outputs.\n'
                    '  3. Keep the backups until the project has been verified.\n'
                )
                self._set_result(text)
                self.status_var.set('✓ Changes applied successfully.')
                self.apply_btn.configure(state='disabled')
                self.plan = None
                messagebox.showinfo(APP_NAME, 'Variant operation completed successfully.', parent=self)
            except Exception as e:
                self.progress['value'] = 0
                self._set_result('✗ Apply failed.\n\n' + str(e) + '\n\nNo further writes were attempted. If writing had begun, rollback from the just-created backups was attempted.')
                self.status_var.set('✗ Apply failed.')
                messagebox.showerror(APP_NAME, str(e), parent=self)

    app = App()
    app.mainloop()
    return 0



# ---------- tabbed Variant Workbench GUI ----------

def run_gui(initial: Optional[str] = None, plugin_mode: bool = False, launch_note: str = '') -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as e:
        print(f'Tkinter is unavailable: {e}', file=sys.stderr)
        return 2

    class Workbench(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f'{APP_NAME} {APP_VERSION}')
            self.geometry('1380x860')
            self.minsize(1040, 680)
            self.analysis: Optional[ProjectAnalysis] = None
            self.matrix_rows: List[MatrixRow] = []
            self.issues: List[LintIssue] = []
            self.sync_issues: List[SyncIssue] = []
            self.pending_patches: Dict[Tuple[str, str, str, str], VariantPatch] = {}
            self.merge_plan: Optional[VariantPlan] = None
            self.release_plan: Optional[ReleasePlan] = None
            self.plugin_mode = plugin_mode

            self.path_var = tk.StringVar(value=initial or '')
            self.status_var = tk.StringVar(value='Open a KiCad project to begin.')
            self.health_var = tk.StringVar(value='Health: —')

            self._setup_styles(ttk)
            self._build_shell(tk, ttk, filedialog, messagebox, launch_note)
            if initial:
                self.after(80, self.load_project)

        def _setup_styles(self, ttkmod) -> None:
            style = ttkmod.Style(self)
            try:
                style.configure('Title.TLabel', font=('TkDefaultFont', 15, 'bold'))
                style.configure('Section.TLabel', font=('TkDefaultFont', 11, 'bold'))
                style.configure('Step.TLabel', font=('TkDefaultFont', 10, 'bold'))
                style.configure('Good.TLabel', foreground='#1f7a1f')
                style.configure('Warn.TLabel', foreground='#9a6700')
                style.configure('Bad.TLabel', foreground='#b42318')
            except Exception:
                pass

        def _build_shell(self, tk, ttk, filedialog, messagebox, launch_note: str) -> None:
            self.tkmod, self.ttk, self.filedialog, self.messagebox = tk, ttk, filedialog, messagebox
            outer = ttk.Frame(self, padding=10)
            outer.pack(fill='both', expand=True)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(2, weight=1)

            hdr = ttk.Frame(outer)
            hdr.grid(row=0, column=0, sticky='ew')
            hdr.columnconfigure(1, weight=1)
            ttk.Label(hdr, text='KiCad Design Variant Workbench', style='Title.TLabel').grid(row=0, column=0, sticky='w')
            badge = f'v{APP_VERSION}' + ('  •  KiCad PCB Editor plugin' if self.plugin_mode else '')
            ttk.Label(hdr, text=badge).grid(row=0, column=1, sticky='w', padx=(10, 0))
            ttk.Label(hdr, textvariable=self.health_var).grid(row=0, column=2, sticky='e')
            ttk.Button(
                hdr,
                text='Help',
                command=lambda: webbrowser.open(Path(__file__).resolve().with_name('help.html').as_uri()),
            ).grid(row=0, column=3, sticky='e', padx=(8, 0))

            projectbar = ttk.LabelFrame(outer, text='Project', padding=7)
            projectbar.grid(row=1, column=0, sticky='ew', pady=(8, 8))
            projectbar.columnconfigure(0, weight=1)
            ttk.Entry(projectbar, textvariable=self.path_var).grid(row=0, column=0, sticky='ew')
            ttk.Button(projectbar, text='Browse…', command=self.browse).grid(row=0, column=1, padx=(7, 0))
            ttk.Button(projectbar, text='Load / Refresh', command=self.load_project).grid(row=0, column=2, padx=(7, 0))
            ttk.Label(projectbar, textvariable=self.status_var).grid(row=1, column=0, columnspan=3, sticky='w', pady=(5, 0))
            if launch_note:
                ttk.Label(projectbar, text=launch_note, wraplength=1100).grid(row=2, column=0, columnspan=3, sticky='w', pady=(3, 0))

            self.nb = ttk.Notebook(outer)
            self.nb.grid(row=2, column=0, sticky='nsew')
            self.tabs: Dict[str, object] = {}
            for key, title in [
                ('dashboard', 'Dashboard'),
                ('merge', 'Merge / Set Default'),
                ('matrix', 'Variant Matrix'),
                ('compare', 'Compare'),
                ('validate', 'Validate'),
                ('sync', 'PCB Sync Audit'),
                ('substitute', 'Part Substitution'),
                ('release', 'Manufacturing Release'),
                ('manage', 'Manage'),
            ]:
                f = ttk.Frame(self.nb, padding=10)
                self.nb.add(f, text=title)
                self.tabs[key] = f

            self._build_dashboard()
            self._build_merge_tab()
            self._build_matrix_tab()
            self._build_compare_tab()
            self._build_validate_tab()
            self._build_sync_tab()
            self._build_substitution_tab()
            self._build_release_tab()
            self._build_manage_tab()

        # ---------- project loading ----------
        def browse(self) -> None:
            p = self.filedialog.askopenfilename(
                title='Select top-level KiCad schematic',
                filetypes=[('KiCad schematic', '*.kicad_sch'), ('All files', '*.*')],
            )
            if p:
                self.path_var.set(p)
                self.load_project()

        def require_project(self) -> bool:
            if self.analysis is None:
                self.messagebox.showinfo(APP_NAME, 'Load a KiCad project first.', parent=self)
                return False
            return True

        def load_project(self) -> None:
            try:
                raw = self.path_var.get().strip()
                if not raw:
                    raise VariantPromoterError('Choose a .kicad_sch file first.')
                root = Path(raw).expanduser().resolve()
                self.analysis = analyze_project(root)
                self.matrix_rows, _ = collect_matrix_rows(root)
                self.issues = lint_project(root)
                self.sync_issues = []
                self.pending_patches.clear()
                self.merge_plan = None
                self.release_plan = None
                self.path_var.set(str(root))
                self._refresh_everything()
                status, e, w, i = health_summary(self.issues)
                self.status_var.set(
                    f'✓ Loaded {root.name}: {self.analysis.schematic_count} schematic(s), '
                    f'{self.analysis.symbol_instances} symbol instance(s), {len(self.analysis.variant_names)} named variant(s).'
                )
                self.health_var.set(f'Health: {status}  •  {e} error / {w} warning / {i} info')
            except Exception as exc:
                self.analysis = None
                self.matrix_rows = []
                self.issues = []
                self.sync_issues = []
                self.status_var.set('✗ Project load failed.')
                self.health_var.set('Health: —')
                self.messagebox.showerror(APP_NAME, str(exc), parent=self)

        def _variant_values(self, include_default: bool = True) -> List[str]:
            vals = list(self.analysis.variant_names) if self.analysis else []
            return ([DEFAULT_VARIANT] + vals) if include_default else vals

        def _refresh_everything(self) -> None:
            self._refresh_dashboard()
            self._refresh_merge_controls()
            self._refresh_matrix()
            self._refresh_compare_controls()
            self._refresh_validation()
            self._refresh_sync_controls()
            self._refresh_substitution_controls()
            self._refresh_release_controls()
            self._refresh_manage_controls()

        # ---------- reusable review/apply dialog ----------
        def review_plan(self, plan: VariantPlan, *, heading: Optional[str] = None, on_success=None) -> None:
            tk, ttk = self.tkmod, self.ttk
            win = tk.Toplevel(self)
            win.title(heading or plan.title)
            win.geometry('1120x720')
            win.transient(self)
            win.grab_set()
            win.columnconfigure(0, weight=1)
            win.rowconfigure(2, weight=1)

            ttk.Label(win, text=heading or plan.title, style='Title.TLabel').grid(row=0, column=0, sticky='w', padx=12, pady=(12, 4))
            summary = '\n'.join('• ' + s for s in plan.summary)
            ttk.Label(win, text=summary, wraplength=1050, justify='left').grid(row=1, column=0, sticky='ew', padx=12, pady=(0, 8))

            frame = ttk.Frame(win)
            frame.grid(row=2, column=0, sticky='nsew', padx=12)
            frame.columnconfigure(0, weight=1); frame.rowconfigure(0, weight=1)
            cols = ('cat','item','prop','before','after','file')
            tree = ttk.Treeview(frame, columns=cols, show='headings')
            labels = {'cat':'Category','item':'Item','prop':'Property','before':'Before','after':'After','file':'File'}
            widths = {'cat':150,'item':120,'prop':180,'before':220,'after':220,'file':150}
            for c in cols:
                tree.heading(c, text=labels[c]); tree.column(c, width=widths[c], stretch=True)
            tree.tag_configure('danger', foreground='#b42318')
            tree.tag_configure('change', foreground='#7a4b00')
            for r in plan.changes:
                tag = 'danger' if 'delete' in r.category.casefold() else 'change'
                tree.insert('', 'end', values=(r.category,r.item,r.property,r.before,r.after,r.file), tags=(tag,))
            tree.grid(row=0, column=0, sticky='nsew')
            sy = ttk.Scrollbar(frame, orient='vertical', command=tree.yview); sy.grid(row=0,column=1,sticky='ns')
            sx = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview); sx.grid(row=1,column=0,sticky='ew')
            tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)

            bottom = ttk.Frame(win); bottom.grid(row=3,column=0,sticky='ew',padx=12,pady=12); bottom.columnconfigure(1,weight=1)
            confirmed = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(bottom, text='I have saved and closed KiCad editors that have this project open.', variable=confirmed)
            chk.grid(row=0,column=0,columnspan=3,sticky='w')
            result = tk.StringVar(value='Step 3 — review above. Step 4 — confirm project is closed, then Apply.')
            ttk.Label(bottom, textvariable=result).grid(row=1,column=0,columnspan=3,sticky='w',pady=(6,6))
            pb = ttk.Progressbar(bottom, mode='determinate', maximum=100); pb.grid(row=2,column=0,columnspan=3,sticky='ew',pady=(0,8))

            def do_apply():
                if not confirmed.get():
                    self.messagebox.showwarning(APP_NAME, 'Close KiCad editors and tick the confirmation first.', parent=win); return
                if not self.messagebox.askyesno(APP_NAME, 'Apply the reviewed changes now?\n\nTimestamped backups will be created first.', parent=win):
                    return
                try:
                    pb['value']=15; win.update_idletasks()
                    backups=apply_plan(plan)
                    pb['value']=100
                    result.set(f'✓ Applied successfully. {len(backups)} backup file(s) created. Reloading project…')
                    win.update_idletasks()
                    self.load_project()
                    if on_success:
                        on_success(backups)
                    self.messagebox.showinfo(APP_NAME, 'Operation completed successfully.', parent=win)
                    win.destroy()
                except Exception as exc:
                    pb['value']=0; result.set('✗ Apply failed; see error dialog.')
                    self.messagebox.showerror(APP_NAME, str(exc), parent=win)

            ttk.Button(bottom, text='Export preview CSV…', command=lambda: self._export_records(plan.changes)).grid(row=3,column=0,sticky='w')
            ttk.Button(bottom, text='Apply reviewed operation', command=do_apply).grid(row=3,column=2,sticky='e')
            ttk.Button(bottom, text='Cancel', command=win.destroy).grid(row=3,column=1,sticky='e',padx=8)

        def _export_records(self, records: Sequence[ChangeRecord]) -> None:
            if not records:
                self.messagebox.showinfo(APP_NAME, 'There are no records to export.', parent=self); return
            p = self.filedialog.asksaveasfilename(defaultextension='.csv', filetypes=[('CSV','*.csv')], initialfile='variant_changes.csv')
            if p:
                export_changes_csv(records, Path(p)); self.status_var.set(f'✓ Exported {len(records)} change record(s).')

        # ---------- Dashboard ----------
        def _build_dashboard(self) -> None:
            ttk = self.ttk; page=self.tabs['dashboard']
            page.columnconfigure(0,weight=1); page.rowconfigure(3,weight=1)
            ttk.Label(page,text='Variant Workbench Dashboard',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='Project-wide view of variant differences, health and the safest next action.').grid(row=1,column=0,sticky='w',pady=(2,10))
            self.dash_cards=ttk.Frame(page); self.dash_cards.grid(row=2,column=0,sticky='ew',pady=(0,10))
            self.dash_card_vars=[self.tkmod.StringVar(value='—') for _ in range(5)]
            for i,(name,var) in enumerate(zip(['Schematics','Symbols','Named variants','Health','Pending edits'],self.dash_card_vars)):
                f=ttk.LabelFrame(self.dash_cards,text=name,padding=8); f.grid(row=0,column=i,sticky='ew',padx=(0 if i==0 else 6,0)); self.dash_cards.columnconfigure(i,weight=1)
                ttk.Label(f,textvariable=var).pack(anchor='w')
            box=ttk.LabelFrame(page,text='Variant overview vs Default',padding=6); box.grid(row=3,column=0,sticky='nsew'); box.columnconfigure(0,weight=1); box.rowconfigure(0,weight=1)
            cols=('diff','dnp','bom','value','fp','fields','flags')
            self.dash_tree=ttk.Treeview(box,columns=cols,show='tree headings')
            self.dash_tree.heading('#0',text='Variant'); self.dash_tree.column('#0',width=190)
            for c,t,w in [('diff','Changed items',110),('dnp','DNP',70),('bom','BOM excl.',80),('value','Value Δ',80),('fp','Footprint Δ',95),('fields','Field Δ',80),('flags','Flag Δ',80)]:
                self.dash_tree.heading(c,text=t); self.dash_tree.column(c,width=w,anchor='center')
            self.dash_tree.grid(row=0,column=0,sticky='nsew'); sy=ttk.Scrollbar(box,orient='vertical',command=self.dash_tree.yview);sy.grid(row=0,column=1,sticky='ns');self.dash_tree.configure(yscrollcommand=sy.set)
            quick=ttk.Frame(page); quick.grid(row=4,column=0,sticky='ew',pady=(8,0))
            ttk.Button(quick,text='Merge a variant into Default →',command=lambda:self.nb.select(self.tabs['merge'])).pack(side='left')
            ttk.Button(quick,text='Validate project',command=lambda:(self.nb.select(self.tabs['validate']),self.run_validation())).pack(side='left',padx=7)
            ttk.Button(quick,text='Audit PCB sync',command=lambda:(self.nb.select(self.tabs['sync']),self.run_sync_audit())).pack(side='left',padx=(0,7))
            ttk.Button(quick,text='Generate manufacturing release',command=lambda:self.nb.select(self.tabs['release'])).pack(side='left')

        def _refresh_dashboard(self) -> None:
            if not hasattr(self,'dash_tree'): return
            for x in self.dash_tree.get_children(): self.dash_tree.delete(x)
            if not self.analysis:
                for v in self.dash_card_vars: v.set('—')
                return
            status,e,w,i=health_summary(self.issues)
            vals=[str(self.analysis.schematic_count),str(self.analysis.symbol_instances),str(len(self.analysis.variant_names)),f'{status} ({e}/{w}/{i})',str(len(self.pending_patches))]
            for var,val in zip(self.dash_card_vars,vals): var.set(val)
            for st in self.analysis.stats:
                self.dash_tree.insert('', 'end', text=st.name, values=(st.differing_instances,st.dnp_instances,st.bom_excluded_instances,st.value_differences,st.footprint_differences,st.field_differences,st.flag_differences))

        # ---------- Merge / Set Default tab ----------
        def _build_merge_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk; page=self.tabs['merge']; page.columnconfigure(0,weight=1); page.rowconfigure(5,weight=1)
            ttk.Label(page,text='Merge variant into Default',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='This is the original core function of the tool. It remains isolated here so changing the project baseline is deliberate and guided.').grid(row=1,column=0,sticky='w',pady=(2,10))
            steps=ttk.Frame(page); steps.grid(row=2,column=0,sticky='ew')
            for i,t in enumerate(['1  Select variant','2  Choose merge behavior','3  Preview semantic rebase','4  Apply with backup']):
                ttk.Label(steps,text=t,style='Step.TLabel').grid(row=0,column=i,sticky='w',padx=(0 if i==0 else 14,0))
            form=ttk.LabelFrame(page,text='Steps 1–2',padding=9); form.grid(row=3,column=0,sticky='ew',pady=(8,8)); form.columnconfigure(1,weight=1)
            self.merge_source=tk.StringVar(); self.merge_mode=tk.StringVar(value='Promote and remove source variant'); self.merge_old_name=tk.StringVar(value='Previous Default')
            ttk.Label(form,text='Variant to become <Default>:').grid(row=0,column=0,sticky='w'); self.merge_combo=ttk.Combobox(form,textvariable=self.merge_source,state='readonly',width=36);self.merge_combo.grid(row=0,column=1,sticky='w',padx=8)
            ttk.Label(form,text='Behavior:').grid(row=1,column=0,sticky='w',pady=(7,0)); self.merge_mode_combo=ttk.Combobox(form,textvariable=self.merge_mode,state='readonly',width=42,values=['Promote and remove source variant','Promote and keep equivalent source variant','Swap with Default and preserve old Default']);self.merge_mode_combo.grid(row=1,column=1,sticky='w',padx=8,pady=(7,0))
            ttk.Label(form,text='Old Default variant name (swap mode):').grid(row=2,column=0,sticky='w',pady=(7,0)); self.merge_old_entry=ttk.Entry(form,textvariable=self.merge_old_name,width=38);self.merge_old_entry.grid(row=2,column=1,sticky='w',padx=8,pady=(7,0))
            ttk.Button(form,text='Step 3 — Preview merge',command=self.preview_merge).grid(row=0,column=2,rowspan=3,sticky='ns',padx=(12,0))
            self.merge_summary=tk.StringVar(value='No merge preview generated.')
            ttk.Label(page,textvariable=self.merge_summary,wraplength=1180,justify='left').grid(row=4,column=0,sticky='ew')
            box=ttk.LabelFrame(page,text='Preview — Default changes and rebase effects',padding=6);box.grid(row=5,column=0,sticky='nsew',pady=(8,0));box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
            self.merge_tree=self._make_change_tree(box)
            btns=ttk.Frame(page);btns.grid(row=6,column=0,sticky='ew',pady=(8,0));
            ttk.Button(btns,text='Export preview CSV…',command=lambda:self._export_records(self.merge_plan.changes if self.merge_plan else [])).pack(side='left')
            self.merge_apply_btn=ttk.Button(btns,text='Step 4 — Review & Apply…',command=self.apply_merge_review,state='disabled');self.merge_apply_btn.pack(side='right')

        def _make_change_tree(self,parent):
            ttk=self.ttk; cols=('cat','item','prop','before','after','file'); tree=ttk.Treeview(parent,columns=cols,show='headings')
            for c,t,w in [('cat','Category',150),('item','Item',110),('prop','Property',170),('before','Before',220),('after','After',220),('file','File',140)]: tree.heading(c,text=t);tree.column(c,width=w,stretch=True)
            tree.grid(row=0,column=0,sticky='nsew');sy=ttk.Scrollbar(parent,orient='vertical',command=tree.yview);sy.grid(row=0,column=1,sticky='ns');sx=ttk.Scrollbar(parent,orient='horizontal',command=tree.xview);sx.grid(row=1,column=0,sticky='ew');tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);return tree

        def _refresh_merge_controls(self) -> None:
            if not hasattr(self,'merge_combo'): return
            vals=self._variant_values(False); self.merge_combo['values']=vals
            if vals and self.merge_source.get() not in vals: self.merge_source.set(vals[0])
            self.merge_plan=None; self.merge_apply_btn.configure(state='disabled'); self.merge_summary.set('No merge preview generated.')
            for x in self.merge_tree.get_children(): self.merge_tree.delete(x)

        def preview_merge(self) -> None:
            if not self.require_project(): return
            try:
                src=self.merge_source.get(); mode=self.merge_mode.get()
                if mode=='Promote and remove source variant': plan=plan_promote_variant(self.analysis.root,src,False)
                elif mode=='Promote and keep equivalent source variant': plan=plan_promote_variant(self.analysis.root,src,True)
                else: plan=plan_swap_default(self.analysis.root,src,self.merge_old_name.get())
                self.merge_plan=plan
                for x in self.merge_tree.get_children(): self.merge_tree.delete(x)
                for r in plan.changes: self.merge_tree.insert('', 'end', values=(r.category,r.item,r.property,r.before,r.after,r.file))
                self.merge_summary.set('\n'.join('• '+x for x in plan.summary))
                self.merge_apply_btn.configure(state='normal')
                self.status_var.set(f'✓ Merge preview ready: {len(plan.changes)} review record(s).')
            except Exception as exc:
                self.merge_plan=None; self.merge_apply_btn.configure(state='disabled'); self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        def apply_merge_review(self) -> None:
            if self.merge_plan: self.review_plan(self.merge_plan,heading='Merge / Set Default — final review')

        # ---------- Variant Matrix ----------
        def _build_matrix_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk; page=self.tabs['matrix'];page.columnconfigure(0,weight=1);page.rowconfigure(4,weight=1)
            ttk.Label(page,text='Variant Matrix',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='Visual project-wide matrix. Select a named variant, then edit component fields/assembly flags without touching Default.').grid(row=1,column=0,sticky='w',pady=(2,8))
            guide=ttk.Frame(page);guide.grid(row=2,column=0,sticky='ew');
            for i,t in enumerate(['1  Choose edit variant','2  Select row / edit','3  Preview pending edits','4  Apply safely']):ttk.Label(guide,text=t,style='Step.TLabel').grid(row=0,column=i,padx=(0 if i==0 else 16,0),sticky='w')
            ctrl=ttk.Frame(page);ctrl.grid(row=3,column=0,sticky='ew',pady=(8,7));ctrl.columnconfigure(6,weight=1)
            self.matrix_variant=tk.StringVar(); self.matrix_filter=tk.StringVar(); self.matrix_pending=tk.StringVar(value='0 pending edits')
            ttk.Label(ctrl,text='Edit variant:').grid(row=0,column=0); self.matrix_variant_combo=ttk.Combobox(ctrl,textvariable=self.matrix_variant,state='readonly',width=28);self.matrix_variant_combo.grid(row=0,column=1,padx=(5,10))
            ttk.Label(ctrl,text='Filter:').grid(row=0,column=2); ttk.Entry(ctrl,textvariable=self.matrix_filter,width=24).grid(row=0,column=3,padx=(5,10))
            ttk.Button(ctrl,text='Edit selected…',command=self.edit_matrix_selected).grid(row=0,column=4,padx=(0,6)); ttk.Button(ctrl,text='Discard pending',command=self.discard_pending).grid(row=0,column=5)
            ttk.Label(ctrl,textvariable=self.matrix_pending).grid(row=0,column=7,sticky='e')
            box=ttk.Frame(page);box.grid(row=4,column=0,sticky='nsew');box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
            self.matrix_tree=ttk.Treeview(box,show='tree headings',selectmode='browse');self.matrix_tree.heading('#0',text='Ref');self.matrix_tree.column('#0',width=100,stretch=False);self.matrix_tree.tag_configure('staged',foreground='#245ea8');self.matrix_tree.tag_configure('different',foreground='#7a4b00');self.matrix_tree.grid(row=0,column=0,sticky='nsew')
            sy=ttk.Scrollbar(box,orient='vertical',command=self.matrix_tree.yview);sy.grid(row=0,column=1,sticky='ns');sx=ttk.Scrollbar(box,orient='horizontal',command=self.matrix_tree.xview);sx.grid(row=1,column=0,sticky='ew');self.matrix_tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
            self.matrix_tree.bind('<Double-1>',lambda e:self.edit_matrix_selected())
            bottom=ttk.Frame(page);bottom.grid(row=5,column=0,sticky='ew',pady=(8,0));
            ttk.Button(bottom,text='Preview pending edits…',command=self.preview_pending_matrix).pack(side='right'); ttk.Label(bottom,text='Tip: DNP/FIT and key value changes are visible directly in each variant column.').pack(side='left')
            self.matrix_filter.trace_add('write',lambda *_:self._refresh_matrix_rows_only()); self.matrix_variant.trace_add('write',lambda *_:self._refresh_matrix_rows_only())

        def _refresh_matrix(self) -> None:
            if not hasattr(self,'matrix_tree'): return
            vals=self._variant_values(False); self.matrix_variant_combo['values']=vals
            if vals and self.matrix_variant.get() not in vals:self.matrix_variant.set(vals[0])
            # Reconfigure dynamic columns: file + Default + every named variant.
            cols=['file',DEFAULT_VARIANT]+vals
            self.matrix_tree['columns']=cols
            for c in cols:
                self.matrix_tree.heading(c,text=c)
                self.matrix_tree.column(c,width=190 if c!= 'file' else 150,stretch=True)
            self._refresh_matrix_rows_only()

        def _effective_with_pending(self,row:MatrixRow,variant:str)->State:
            st=row.states[variant].clone()
            k=(row.key.split('|',1)[0].casefold(),row.uuid,row.instance_path,variant.casefold())
            p=self.pending_patches.get(k)
            return _apply_patch_to_state(st,p) if p else st

        def _refresh_matrix_rows_only(self) -> None:
            if not hasattr(self,'matrix_tree'):return
            for x in self.matrix_tree.get_children():self.matrix_tree.delete(x)
            if not self.analysis:return
            needle=self.matrix_filter.get().strip().casefold(); vals=self._variant_values(False)
            for idx,row in enumerate(self.matrix_rows):
                hay=' '.join([row.reference,row.file,row.kind,row.instance_path]+[v.fields.get('Value','')+' '+v.fields.get('MPN','') for v in row.states.values()]).casefold()
                if needle and needle not in hay:continue
                values=[row.file,format_state_compact(row.states[DEFAULT_VARIANT])]
                for v in vals:values.append(format_state_compact(self._effective_with_pending(row,v),row.states[DEFAULT_VARIANT]))
                edit_v=self.matrix_variant.get();tag=''
                if edit_v:
                    k=(row.key.split('|',1)[0].casefold(),row.uuid,row.instance_path,edit_v.casefold())
                    if k in self.pending_patches:tag='staged'
                    elif edit_v in row.states and row.states[edit_v].signature()!=row.states[DEFAULT_VARIANT].signature():tag='different'
                self.matrix_tree.insert('', 'end', iid=str(idx), text=row.reference, values=values,tags=((tag,) if tag else ()))
            self.matrix_pending.set(f'{len(self.pending_patches)} pending edit target(s)')
            self._refresh_dashboard()

        def edit_matrix_selected(self) -> None:
            if not self.require_project():return
            sel=self.matrix_tree.selection(); variant=self.matrix_variant.get()
            if not sel or not variant:
                self.messagebox.showinfo(APP_NAME,'Select a matrix row and named edit variant first.',parent=self);return
            row=self.matrix_rows[int(sel[0])]
            self._open_state_editor(row,variant,'Matrix edit')

        def _open_state_editor(self,row:MatrixRow,variant:str,title:str,substitution_mode:bool=False) -> None:
            tk,ttk=self.tkmod,self.ttk
            cur=self._effective_with_pending(row,variant); base=row.states[DEFAULT_VARIANT]
            win=tk.Toplevel(self);win.title(f'{title}: {row.reference} — {variant}');win.transient(self);win.grab_set();win.columnconfigure(1,weight=1)
            ttk.Label(win,text=f'{row.reference}  •  {row.file}',style='Title.TLabel').grid(row=0,column=0,columnspan=3,sticky='w',padx=12,pady=(12,6))
            ttk.Label(win,text=f'Default: {format_state_compact(base)}\nCurrent {variant}: {format_state_compact(cur,base)}').grid(row=1,column=0,columnspan=3,sticky='w',padx=12,pady=(0,8))
            fields=['Value','Footprint','Manufacturer','MPN']; vars={}
            for i,name in enumerate(fields,start=2):
                ttk.Label(win,text=name+':').grid(row=i,column=0,sticky='w',padx=(12,6),pady=4);v=tk.StringVar(value=cur.fields.get(name,''));vars[name]=v;ttk.Entry(win,textvariable=v,width=75).grid(row=i,column=1,columnspan=2,sticky='ew',padx=(0,12),pady=4)
            dnp=tk.BooleanVar(value=cur.dnp);bom=tk.BooleanVar(value=cur.excluded_from_bom);pos=tk.BooleanVar(value=cur.excluded_from_pos);board=tk.BooleanVar(value=cur.excluded_from_board);sim=tk.BooleanVar(value=cur.exclude_from_sim)
            flags=ttk.LabelFrame(win,text='Assembly flags',padding=7);flags.grid(row=6,column=0,columnspan=3,sticky='ew',padx=12,pady=8)
            for j,(text,var) in enumerate([('DNP',dnp),('Exclude BOM',bom),('Exclude position',pos),('Exclude board',board),('Exclude simulation',sim)]):ttk.Checkbutton(flags,text=text,variable=var).grid(row=0,column=j,padx=(0,10))
            pinok=tk.BooleanVar(value=False); fpok=tk.BooleanVar(value=False)
            if substitution_mode:
                compat=ttk.LabelFrame(win,text='Substitution safety',padding=7);compat.grid(row=7,column=0,columnspan=3,sticky='ew',padx=12,pady=(0,8))
                ttk.Checkbutton(compat,text='I verified electrical pin/function compatibility.',variable=pinok).pack(anchor='w')
                ttk.Checkbutton(compat,text='If the footprint changes, I verified pad mapping and mechanical compatibility.',variable=fpok).pack(anchor='w')
                ttk.Label(compat,text='KiCad 10 safe mode: this workbench changes variant fields/assembly attributes only; it does not invent a custom pin-map override.').pack(anchor='w',pady=(4,0))
            info=tk.StringVar(value='Changes are staged only; nothing is written until Preview → Apply.')
            ttk.Label(win,textvariable=info).grid(row=8,column=0,columnspan=3,sticky='w',padx=12,pady=(2,8))
            def save():
                if substitution_mode and not pinok.get():
                    self.messagebox.showwarning(APP_NAME,'Confirm electrical pin/function compatibility before staging a substitution.',parent=win);return
                if substitution_mode and vars['Footprint'].get()!=cur.fields.get('Footprint','') and not fpok.get():
                    self.messagebox.showwarning(APP_NAME,'The footprint changes. Confirm pad mapping/mechanical compatibility.',parent=win);return
                updates={name:v.get() for name,v in vars.items() if v.get()!=cur.fields.get(name,'')}
                patch=VariantPatch(file=row.key.split('|',1)[0],uuid=row.uuid,instance_path=row.instance_path,variant=variant,field_updates=updates,
                                   dnp=dnp.get() if dnp.get()!=cur.dnp else None,
                                   excluded_from_bom=bom.get() if bom.get()!=cur.excluded_from_bom else None,
                                   excluded_from_pos=pos.get() if pos.get()!=cur.excluded_from_pos else None,
                                   excluded_from_board=board.get() if board.get()!=cur.excluded_from_board else None,
                                   exclude_from_sim=sim.get() if sim.get()!=cur.exclude_from_sim else None)
                key=(row.key.split('|',1)[0].casefold(),row.uuid,row.instance_path,variant.casefold())
                if not updates and all(getattr(patch,a) is None for a in ('dnp','excluded_from_bom','excluded_from_pos','excluded_from_board','exclude_from_sim')):
                    self.pending_patches.pop(key,None)
                else:self.pending_patches[key]=patch
                self._refresh_matrix_rows_only();self._refresh_substitution_preview();win.destroy();self.status_var.set(f'✓ Staged edit for {row.reference} / {variant}.')
            btn=ttk.Frame(win);btn.grid(row=9,column=0,columnspan=3,sticky='e',padx=12,pady=(0,12));ttk.Button(btn,text='Cancel',command=win.destroy).pack(side='right');ttk.Button(btn,text='Stage edit',command=save).pack(side='right',padx=(0,7))

        def discard_pending(self) -> None:
            self.pending_patches.clear();self._refresh_matrix_rows_only();self._refresh_substitution_preview();self.status_var.set('Pending matrix/substitution edits discarded.')

        def preview_pending_matrix(self) -> None:
            if not self.require_project():return
            try:
                plan=plan_patch_variants(self.analysis.root,list(self.pending_patches.values()),'Apply Variant Matrix / Substitution edits')
                self.review_plan(plan,heading='Variant Matrix — final review',on_success=lambda _:self.pending_patches.clear())
            except Exception as exc:self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        # ---------- Compare ----------
        def _build_compare_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk;page=self.tabs['compare'];page.columnconfigure(0,weight=1);page.rowconfigure(3,weight=1)
            ttk.Label(page,text='Compare Variants',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ctrl=ttk.Frame(page);ctrl.grid(row=1,column=0,sticky='ew',pady=(8,8));
            self.cmp_left=tk.StringVar(value=DEFAULT_VARIANT);self.cmp_right=tk.StringVar();self.cmp_filter=tk.StringVar();self.cmp_records=[]
            ttk.Label(ctrl,text='From:').pack(side='left');self.cmp_left_combo=ttk.Combobox(ctrl,textvariable=self.cmp_left,state='readonly',width=26);self.cmp_left_combo.pack(side='left',padx=(5,10));ttk.Label(ctrl,text='To:').pack(side='left');self.cmp_right_combo=ttk.Combobox(ctrl,textvariable=self.cmp_right,state='readonly',width=26);self.cmp_right_combo.pack(side='left',padx=(5,10));ttk.Button(ctrl,text='Compare',command=self.run_compare).pack(side='left');ttk.Label(ctrl,text='Filter:').pack(side='left',padx=(16,5));ttk.Entry(ctrl,textvariable=self.cmp_filter,width=25).pack(side='left');ttk.Button(ctrl,text='Export CSV…',command=lambda:self._export_records(self.cmp_records)).pack(side='right')
            self.cmp_summary=tk.StringVar(value='Choose two configurations to compare.');ttk.Label(page,textvariable=self.cmp_summary).grid(row=2,column=0,sticky='w')
            box=ttk.Frame(page);box.grid(row=3,column=0,sticky='nsew',pady=(6,0));box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1);self.cmp_tree=self._make_change_tree(box)
            self.cmp_filter.trace_add('write',lambda *_:self._refresh_compare_tree())

        def _refresh_compare_controls(self) -> None:
            if not hasattr(self,'cmp_left_combo'):return
            vals=self._variant_values(True);self.cmp_left_combo['values']=vals;self.cmp_right_combo['values']=vals
            if vals and self.cmp_left.get() not in vals:self.cmp_left.set(DEFAULT_VARIANT)
            if vals and self.cmp_right.get() not in vals:self.cmp_right.set(vals[1] if len(vals)>1 else vals[0])
            self.cmp_records=[];self._refresh_compare_tree()

        def run_compare(self) -> None:
            if not self.require_project():return
            try:self.cmp_records=compare_variants(self.analysis.root,self.cmp_left.get(),self.cmp_right.get());self.cmp_summary.set(f'{len(self.cmp_records)} differing properties. Read-only.');self._refresh_compare_tree()
            except Exception as exc:self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        def _refresh_compare_tree(self) -> None:
            if not hasattr(self,'cmp_tree'):return
            for x in self.cmp_tree.get_children():self.cmp_tree.delete(x)
            needle=self.cmp_filter.get().strip().casefold() if hasattr(self,'cmp_filter') else ''
            for r in getattr(self,'cmp_records',[]):
                if needle and needle not in ' '.join(dataclasses.astuple(r)).casefold():continue
                self.cmp_tree.insert('', 'end', values=(r.category,r.item,r.property,r.before,r.after,r.file))

        # ---------- Validate ----------
        def _build_validate_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk;page=self.tabs['validate'];page.columnconfigure(0,weight=1);page.rowconfigure(3,weight=1)
            ttk.Label(page,text='Variant Health / Lint',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='Project-aware checks for stale metadata, redundant overrides, footprint divergence and manufacturing-sensitive flag combinations.').grid(row=1,column=0,sticky='w',pady=(2,8))
            ctrl=ttk.Frame(page);ctrl.grid(row=2,column=0,sticky='ew');self.val_summary=tk.StringVar(value='Not run.');ttk.Button(ctrl,text='Run validation',command=self.run_validation).pack(side='left');ttk.Button(ctrl,text='Clean redundant overrides…',command=self.clean_from_validation).pack(side='left',padx=7);ttk.Label(ctrl,textvariable=self.val_summary).pack(side='left',padx=12)
            box=ttk.Frame(page);box.grid(row=3,column=0,sticky='nsew',pady=(8,0));box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
            cols=('severity','code','item','variant','message','file');self.val_tree=ttk.Treeview(box,columns=cols,show='headings')
            for c,t,w in [('severity','Severity',80),('code','Check',190),('item','Item',100),('variant','Variant',130),('message','Finding',590),('file','File',150)]:self.val_tree.heading(c,text=t);self.val_tree.column(c,width=w,stretch=True)
            self.val_tree.tag_configure('ERROR',foreground='#b42318');self.val_tree.tag_configure('WARNING',foreground='#9a6700');self.val_tree.tag_configure('INFO',foreground='#245ea8');self.val_tree.grid(row=0,column=0,sticky='nsew');sy=ttk.Scrollbar(box,orient='vertical',command=self.val_tree.yview);sy.grid(row=0,column=1,sticky='ns');self.val_tree.configure(yscrollcommand=sy.set)

        def run_validation(self) -> None:
            if not self.require_project():return
            try:self.issues=lint_project(self.analysis.root);self._refresh_validation();status,e,w,i=health_summary(self.issues);self.health_var.set(f'Health: {status}  •  {e} error / {w} warning / {i} info');self._refresh_dashboard();self.status_var.set(f'✓ Validation complete: {status}.')
            except Exception as exc:self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        def _refresh_validation(self) -> None:
            if not hasattr(self,'val_tree'):return
            for x in self.val_tree.get_children():self.val_tree.delete(x)
            for issue in self.issues:self.val_tree.insert('', 'end',values=(issue.severity,issue.code,issue.item,issue.variant,issue.message,issue.file),tags=(issue.severity,))
            status,e,w,i=health_summary(self.issues);self.val_summary.set(f'{status}: {e} error • {w} warning • {i} info')

        def clean_from_validation(self) -> None:
            if not self.require_project():return
            try:self.review_plan(plan_clean_overrides(self.analysis.root),heading='Clean redundant variant overrides')
            except Exception as exc:self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        # ---------- PCB Sync Audit ----------
        def _build_sync_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk;page=self.tabs['sync'];page.columnconfigure(0,weight=1);page.rowconfigure(4,weight=1)
            ttk.Label(page,text='Schematic ↔ PCB Variant Sync Audit',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='Read-only check of variant metadata, DNP/BOM/POS state, Value/Footprint and variant-specific fields before manufacturing.').grid(row=1,column=0,sticky='w',pady=(2,8))
            ctrl=ttk.LabelFrame(page,text='Steps 1–2 — choose scope and audit',padding=8);ctrl.grid(row=2,column=0,sticky='ew');ctrl.columnconfigure(3,weight=1)
            self.sync_variant=tk.StringVar(value='<All variants>');self.sync_board=tk.StringVar(value='');self.sync_summary_var=tk.StringVar(value='Not run.')
            ttk.Label(ctrl,text='Scope:').grid(row=0,column=0,sticky='w');self.sync_variant_combo=ttk.Combobox(ctrl,textvariable=self.sync_variant,state='readonly',width=28);self.sync_variant_combo.grid(row=0,column=1,sticky='w',padx=(5,14))
            ttk.Button(ctrl,text='Run PCB sync audit',command=self.run_sync_audit).grid(row=0,column=2,sticky='w')
            ttk.Label(ctrl,textvariable=self.sync_summary_var).grid(row=0,column=3,sticky='w',padx=12)
            ttk.Label(ctrl,text='Detected board:').grid(row=1,column=0,sticky='w',pady=(7,0));ttk.Label(ctrl,textvariable=self.sync_board).grid(row=1,column=1,columnspan=3,sticky='w',padx=(5,0),pady=(7,0))
            actions=ttk.Frame(page);actions.grid(row=3,column=0,sticky='ew',pady=(8,4))
            ttk.Button(actions,text='Repair guidance…',command=self.show_sync_guidance).pack(side='left')
            ttk.Button(actions,text='Export audit CSV…',command=self.export_sync_csv).pack(side='left',padx=7)
            box=ttk.Frame(page);box.grid(row=4,column=0,sticky='nsew');box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
            cols=('severity','ref','variant','prop','sch','pcb','message');self.sync_tree=ttk.Treeview(box,columns=cols,show='headings')
            for c,t,w in [('severity','Severity',75),('ref','Ref',80),('variant','Variant',130),('prop','Property',165),('sch','Schematic',180),('pcb','PCB',180),('message','Finding',480)]:self.sync_tree.heading(c,text=t);self.sync_tree.column(c,width=w,stretch=True)
            self.sync_tree.tag_configure('ERROR',foreground='#b42318');self.sync_tree.tag_configure('WARNING',foreground='#9a6700');self.sync_tree.tag_configure('INFO',foreground='#555555')
            self.sync_tree.grid(row=0,column=0,sticky='nsew');sy=ttk.Scrollbar(box,orient='vertical',command=self.sync_tree.yview);sy.grid(row=0,column=1,sticky='ns');sx=ttk.Scrollbar(box,orient='horizontal',command=self.sync_tree.xview);sx.grid(row=1,column=0,sticky='ew');self.sync_tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)

        def _refresh_sync_controls(self) -> None:
            if not hasattr(self,'sync_variant_combo'):return
            vals=['<All variants>']+self._variant_values(True);self.sync_variant_combo['values']=vals
            if self.sync_variant.get() not in vals:self.sync_variant.set('<All variants>')
            board=find_board_file(self.analysis.root) if self.analysis else None
            self.sync_board.set(str(board) if board else 'No .kicad_pcb detected')
            self.sync_issues=[];self.sync_summary_var.set('Not run.')
            for x in self.sync_tree.get_children():self.sync_tree.delete(x)

        def run_sync_audit(self) -> None:
            if not self.require_project():return
            try:
                scope=self.sync_variant.get() if hasattr(self,'sync_variant') else '<All variants>'
                selected=None if scope=='<All variants>' else scope
                board,issues=audit_pcb_sync(self.analysis.root,selected);self.sync_issues=issues
                self.sync_board.set(str(board) if board else 'No .kicad_pcb detected')
                for x in self.sync_tree.get_children():self.sync_tree.delete(x)
                for issue in issues:self.sync_tree.insert('', 'end',values=(issue.severity,issue.reference,issue.variant,issue.property,issue.schematic,issue.pcb,issue.message),tags=(issue.severity,))
                status,e,w,i=sync_summary(issues);self.sync_summary_var.set(f'{status}  •  {e} error / {w} warning / {i} info')
                self.status_var.set(f'PCB sync audit: {status}.')
            except Exception as exc:self.sync_issues=[];self.sync_summary_var.set('Audit failed.');self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        def show_sync_guidance(self) -> None:
            self.messagebox.showinfo(APP_NAME,
                'Recommended repair workflow:\n\n'
                '1. Save the schematic and PCB.\n'
                '2. In KiCad run Tools → Update PCB from Schematic.\n'
                '3. Review footprint additions/changes, especially any variant-specific Footprint substitutions.\n'
                '4. Save the PCB.\n'
                '5. Reload this Workbench and run PCB Sync Audit again.\n\n'
                'The audit is intentionally read-only; it does not rewrite .kicad_pcb variant data behind KiCad.',parent=self)

        def export_sync_csv(self) -> None:
            if not self.sync_issues:self.messagebox.showinfo(APP_NAME,'Run a PCB sync audit first.',parent=self);return
            p=self.filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='pcb_variant_sync_audit.csv')
            if not p:return
            with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(['Severity','Reference','Variant','Property','Schematic','PCB','Finding'])
                for i in self.sync_issues:w.writerow([i.severity,i.reference,i.variant,i.property,i.schematic,i.pcb,i.message])
            self.status_var.set(f'✓ Exported {len(self.sync_issues)} PCB sync finding(s).')

        # ---------- Substitution ----------
        def _build_substitution_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk;page=self.tabs['substitute'];page.columnconfigure(0,weight=1);page.rowconfigure(3,weight=1)
            ttk.Label(page,text='Part Substitution',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='Stage variant-specific Value / Footprint / Manufacturer / MPN substitutions with explicit compatibility checks. KiCad 10 safe mode does not write custom pin-map overrides.').grid(row=1,column=0,sticky='w',pady=(2,8))
            ctrl=ttk.Frame(page);ctrl.grid(row=2,column=0,sticky='ew');self.sub_variant=tk.StringVar();self.sub_filter=tk.StringVar();self.sub_variant_combo=ttk.Combobox(ctrl,textvariable=self.sub_variant,state='readonly',width=28);ttk.Label(ctrl,text='Variant:').pack(side='left');self.sub_variant_combo.pack(side='left',padx=(5,12));ttk.Label(ctrl,text='Find reference/part:').pack(side='left');ttk.Entry(ctrl,textvariable=self.sub_filter,width=28).pack(side='left',padx=(5,8));ttk.Button(ctrl,text='Edit substitution…',command=self.edit_substitution).pack(side='left');ttk.Button(ctrl,text='Preview all staged edits…',command=self.preview_pending_matrix).pack(side='right')
            box=ttk.Frame(page);box.grid(row=3,column=0,sticky='nsew',pady=(8,0));box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
            cols=('file','default_value','variant_value','default_fp','variant_fp','default_mpn','variant_mpn','status');self.sub_tree=ttk.Treeview(box,columns=cols,show='tree headings');self.sub_tree.heading('#0',text='Ref');self.sub_tree.column('#0',width=90)
            for c,t,w in [('file','File',130),('default_value','Default value',130),('variant_value','Variant value',130),('default_fp','Default footprint',230),('variant_fp','Variant footprint',230),('default_mpn','Default MPN',150),('variant_mpn','Variant MPN',150),('status','State',90)]:self.sub_tree.heading(c,text=t);self.sub_tree.column(c,width=w,stretch=True)
            self.sub_tree.grid(row=0,column=0,sticky='nsew');sy=ttk.Scrollbar(box,orient='vertical',command=self.sub_tree.yview);sy.grid(row=0,column=1,sticky='ns');sx=ttk.Scrollbar(box,orient='horizontal',command=self.sub_tree.xview);sx.grid(row=1,column=0,sticky='ew');self.sub_tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);self.sub_tree.bind('<Double-1>',lambda e:self.edit_substitution())
            self.sub_filter.trace_add('write',lambda *_:self._refresh_substitution_preview());self.sub_variant.trace_add('write',lambda *_:self._refresh_substitution_preview())

        def _refresh_substitution_controls(self) -> None:
            if not hasattr(self,'sub_variant_combo'):return
            vals=self._variant_values(False);self.sub_variant_combo['values']=vals
            if vals and self.sub_variant.get() not in vals:self.sub_variant.set(vals[0])
            self._refresh_substitution_preview()

        def _refresh_substitution_preview(self) -> None:
            if not hasattr(self,'sub_tree'):return
            for x in self.sub_tree.get_children():self.sub_tree.delete(x)
            if not self.analysis:return
            v=self.sub_variant.get();needle=self.sub_filter.get().strip().casefold()
            if not v:return
            for idx,row in enumerate(self.matrix_rows):
                if row.kind!='symbol':continue
                cur=self._effective_with_pending(row,v);base=row.states[DEFAULT_VARIANT]
                hay=' '.join([row.reference,row.file,base.fields.get('Value',''),cur.fields.get('Value',''),base.fields.get('MPN',''),cur.fields.get('MPN','')]).casefold()
                if needle and needle not in hay:continue
                key=(row.key.split('|',1)[0].casefold(),row.uuid,row.instance_path,v.casefold());status='STAGED' if key in self.pending_patches else ('DIFF' if cur.signature()!=base.signature() else '=Default')
                self.sub_tree.insert('', 'end',iid=str(idx),text=row.reference,values=(row.file,base.fields.get('Value',''),cur.fields.get('Value',''),base.fields.get('Footprint',''),cur.fields.get('Footprint',''),base.fields.get('MPN',''),cur.fields.get('MPN',''),status))

        def edit_substitution(self) -> None:
            if not self.require_project():return
            sel=self.sub_tree.selection();v=self.sub_variant.get()
            if not sel or not v:self.messagebox.showinfo(APP_NAME,'Select a part and named variant first.',parent=self);return
            self._open_state_editor(self.matrix_rows[int(sel[0])],v,'Part substitution',True)

        # ---------- Release ----------
        def _build_release_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk;page=self.tabs['release'];page.columnconfigure(0,weight=1);page.rowconfigure(5,weight=1)
            ttk.Label(page,text='Manufacturing Release',style='Title.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text='Generate a variant-specific release using KiCad CLI, then create a SHA-256 manifest and optional ZIP.').grid(row=1,column=0,sticky='w',pady=(2,8))
            form=ttk.LabelFrame(page,text='Steps 1–2 — configuration',padding=8);form.grid(row=2,column=0,sticky='ew');form.columnconfigure(1,weight=1)
            self.rel_variant=tk.StringVar();self.rel_out=tk.StringVar();self.rel_cli=tk.StringVar();self.rel_zip=tk.BooleanVar(value=True)
            self.rel_require_sync=tk.BooleanVar(value=True);self.rel_bom=tk.BooleanVar(value=True);self.rel_schpdf=tk.BooleanVar(value=True);self.rel_gerber=tk.BooleanVar(value=True);self.rel_drill=tk.BooleanVar(value=True);self.rel_pos=tk.BooleanVar(value=True);self.rel_pcbpdf=tk.BooleanVar(value=True);self.rel_step=tk.BooleanVar(value=False);self.rel_erc=tk.BooleanVar(value=True);self.rel_drc=tk.BooleanVar(value=True)
            ttk.Label(form,text='Variant:').grid(row=0,column=0,sticky='w');self.rel_variant_combo=ttk.Combobox(form,textvariable=self.rel_variant,state='readonly',width=30);self.rel_variant_combo.grid(row=0,column=1,sticky='w',padx=6)
            ttk.Label(form,text='Output folder:').grid(row=1,column=0,sticky='w',pady=5);ttk.Entry(form,textvariable=self.rel_out).grid(row=1,column=1,sticky='ew',padx=6);ttk.Button(form,text='Browse…',command=self.browse_release_out).grid(row=1,column=2)
            ttk.Label(form,text='kicad-cli:').grid(row=2,column=0,sticky='w');ttk.Entry(form,textvariable=self.rel_cli).grid(row=2,column=1,sticky='ew',padx=6);ttk.Button(form,text='Browse…',command=self.browse_cli).grid(row=2,column=2)
            opts=ttk.Frame(form);opts.grid(row=3,column=0,columnspan=3,sticky='w',pady=(8,0))
            for text,var in [('Require PCB sync',self.rel_require_sync),('ERC',self.rel_erc),('BOM',self.rel_bom),('Schematic PDF',self.rel_schpdf),('DRC + parity',self.rel_drc),('Gerbers',self.rel_gerber),('Drill',self.rel_drill),('Position CSV',self.rel_pos),('Assembly PDF',self.rel_pcbpdf),('STEP',self.rel_step),('ZIP package',self.rel_zip)]:ttk.Checkbutton(opts,text=text,variable=var).pack(side='left',padx=(0,10))
            actions=ttk.Frame(page);actions.grid(row=3,column=0,sticky='ew',pady=(8,4));ttk.Button(actions,text='Step 3 — Preview CLI commands',command=self.preview_release).pack(side='left');self.rel_generate_btn=ttk.Button(actions,text='Step 4 — Generate release',command=self.generate_release,state='disabled');self.rel_generate_btn.pack(side='right');self.rel_progress=ttk.Progressbar(actions,mode='determinate',maximum=100,length=260);self.rel_progress.pack(side='right',padx=10)
            self.rel_summary=tk.StringVar(value='No release preview generated.');ttk.Label(page,textvariable=self.rel_summary,wraplength=1180).grid(row=4,column=0,sticky='ew')
            self.rel_log=tk.Text(page,height=16,wrap='none');self.rel_log.grid(row=5,column=0,sticky='nsew',pady=(7,0))

        def _refresh_release_controls(self) -> None:
            if not hasattr(self,'rel_variant_combo'):return
            vals=self._variant_values(True);self.rel_variant_combo['values']=vals
            if vals and self.rel_variant.get() not in vals:self.rel_variant.set(vals[1] if len(vals)>1 else vals[0])
            if self.analysis:
                stem=self.analysis.root.stem;variant=(self.rel_variant.get() or 'Default').replace('<','').replace('>','').replace(' ','_')
                if not self.rel_out.get():self.rel_out.set(str(self.analysis.root.parent/'Manufacturing'/f'{stem}_{variant}'))
                cli=find_kicad_cli();
                if cli:self.rel_cli.set(str(cli))
            self.release_plan=None;self.rel_generate_btn.configure(state='disabled')

        def browse_release_out(self) -> None:
            p=self.filedialog.askdirectory(title='Choose release output parent/folder');
            if p:self.rel_out.set(p)
        def browse_cli(self) -> None:
            p=self.filedialog.askopenfilename(title='Select kicad-cli',filetypes=[('Executable','*.exe'),('All files','*.*')]);
            if p:self.rel_cli.set(p)

        def preview_release(self) -> None:
            if not self.require_project():return
            try:
                self.issues=lint_project(self.analysis.root);status,e,w,i=health_summary(self.issues)
                if e:
                    raise VariantPromoterError(f'Variant health is BLOCKED by {e} error(s). Resolve errors in Validate before manufacturing release.')
                sync_note=''
                if self.rel_require_sync.get() and find_board_file(self.analysis.root):
                    _,sync_issues=audit_pcb_sync(self.analysis.root,self.rel_variant.get())
                    sync_status,se,sw,si=sync_summary(sync_issues)
                    if se:
                        raise VariantPromoterError(f'PCB variant state is OUT OF SYNC ({se} error(s)). Run the PCB Sync Audit tab and Update PCB from Schematic before release, or explicitly disable the sync gate if this is intentional.')
                    sync_note=f' PCB sync {sync_status} ({sw} warning).'
                plan=build_release_plan(self.analysis.root,self.rel_variant.get(),Path(self.rel_out.get()),cli_path=Path(self.rel_cli.get()) if self.rel_cli.get().strip() else None,
                                        include_bom=self.rel_bom.get(),include_schematic_pdf=self.rel_schpdf.get(),include_gerbers=self.rel_gerber.get(),include_drill=self.rel_drill.get(),include_pos=self.rel_pos.get(),include_board_pdf=self.rel_pcbpdf.get(),include_step=self.rel_step.get(),include_erc=self.rel_erc.get(),include_drc=self.rel_drc.get())
                self.release_plan=plan;self.rel_log.delete('1.0','end')
                for task in plan.tasks:self.rel_log.insert('end',f'[{task.label}]\n{subprocess.list2cmdline(task.command)}\n\n')
                board=plan.board_file.name if plan.board_file else 'No PCB detected — schematic outputs only'
                self.rel_summary.set(f'Health {status} ({w} warning).{sync_note} Variant {plan.variant}. Board: {board}. {len(plan.tasks)} CLI task(s). Output: {plan.output_dir}')
                self.rel_generate_btn.configure(state='normal')
            except Exception as exc:self.release_plan=None;self.rel_generate_btn.configure(state='disabled');self.messagebox.showerror(APP_NAME,str(exc),parent=self)

        def generate_release(self) -> None:
            if not self.release_plan:return
            if not self.messagebox.askyesno(APP_NAME,f'Generate manufacturing release for {self.release_plan.variant}?\n\nExisting files with the same names may be replaced by kicad-cli.',parent=self):return
            try:
                self.rel_progress['value']=0;self.rel_generate_btn.configure(state='disabled');self.update_idletasks()
                def progress(done,total,label):
                    self.rel_progress['value']=100*(done/max(1,total));self.rel_summary.set(f'Generating: {label} ({done}/{total})');self.update_idletasks()
                manifest,log=run_release_plan(self.release_plan,zip_release=self.rel_zip.get(),progress_cb=progress);self.rel_progress['value']=100;self.rel_log.insert('end','\n'.join(log)+'\n');self.rel_summary.set(f'✓ Release complete. Manifest: {manifest}');self.status_var.set('✓ Manufacturing release generated.')
                self.messagebox.showinfo(APP_NAME,f'Release generated successfully.\n\n{manifest}',parent=self)
            except Exception as exc:self.rel_progress['value']=0;self.rel_log.insert('end','\nERROR: '+str(exc)+'\n');self.messagebox.showerror(APP_NAME,str(exc),parent=self)
            finally:self.rel_generate_btn.configure(state='normal' if self.release_plan else 'disabled')

        # ---------- Manage ----------
        def _build_manage_tab(self) -> None:
            tk,ttk=self.tkmod,self.ttk;page=self.tabs['manage'];page.columnconfigure(1,weight=1)
            ttk.Label(page,text='Manage Variants',style='Title.TLabel').grid(row=0,column=0,columnspan=2,sticky='w')
            ttk.Label(page,text='Lower-risk naming and lifecycle operations. Changing which configuration is Default remains in the dedicated Merge / Set Default tab.').grid(row=1,column=0,columnspan=2,sticky='w',pady=(2,10))
            self.mgr_op=tk.StringVar(value='Rename variant');self.mgr_src=tk.StringVar();self.mgr_target=tk.StringVar()
            ttk.Label(page,text='Operation:').grid(row=2,column=0,sticky='w',pady=5);self.mgr_op_combo=ttk.Combobox(page,textvariable=self.mgr_op,state='readonly',width=32,values=['Rename variant','Duplicate / create variant','Delete variant','Clean redundant overrides']);self.mgr_op_combo.grid(row=2,column=1,sticky='w')
            ttk.Label(page,text='Source:').grid(row=3,column=0,sticky='w',pady=5);self.mgr_src_combo=ttk.Combobox(page,textvariable=self.mgr_src,state='readonly',width=32);self.mgr_src_combo.grid(row=3,column=1,sticky='w')
            ttk.Label(page,text='New name:').grid(row=4,column=0,sticky='w',pady=5);ttk.Entry(page,textvariable=self.mgr_target,width=35).grid(row=4,column=1,sticky='w')
            ttk.Button(page,text='Preview operation…',command=self.preview_manage).grid(row=5,column=1,sticky='w',pady=(10,0))
            self.mgr_help=tk.StringVar(value='');ttk.Label(page,textvariable=self.mgr_help,wraplength=900).grid(row=6,column=0,columnspan=2,sticky='w',pady=(12,0));self.mgr_op.trace_add('write',lambda *_:self._refresh_manage_controls())

        def _refresh_manage_controls(self) -> None:
            if not hasattr(self,'mgr_src_combo'):return
            op=self.mgr_op.get();vals=self._variant_values(False)
            if op=='Duplicate / create variant':vals=self._variant_values(True)
            self.mgr_src_combo['values']=vals
            if vals and self.mgr_src.get() not in vals:self.mgr_src.set(vals[0])
            self.mgr_help.set({'Rename variant':'Rename everywhere while preserving effective behavior and metadata.','Duplicate / create variant':'Clone a named variant or <Default> into a new named variant.','Delete variant':'Remove the selected named variant; all others remain unchanged.','Clean redundant overrides':'Rebuild variant blocks from effective states and remove serialized no-op overrides.'}.get(op,''))

        def preview_manage(self) -> None:
            if not self.require_project():return
            try:
                op=self.mgr_op.get();root=self.analysis.root
                if op=='Rename variant':plan=plan_rename_variant(root,self.mgr_src.get(),self.mgr_target.get())
                elif op=='Duplicate / create variant':plan=plan_duplicate_variant(root,self.mgr_src.get(),self.mgr_target.get())
                elif op=='Delete variant':plan=plan_delete_variant(root,self.mgr_src.get())
                elif op=='Clean redundant overrides':plan=plan_clean_overrides(root)
                else:raise VariantPromoterError('Unknown management operation.')
                self.review_plan(plan,heading='Manage Variants — review')
            except Exception as exc:self.messagebox.showerror(APP_NAME,str(exc),parent=self)

    app=Workbench();app.mainloop();return 0

# ---------- CLI ----------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=f'{APP_NAME} {APP_VERSION}')
    parser.add_argument('schematic', nargs='?', help='Root/top-level .kicad_sch')
    parser.add_argument('--list', action='store_true', help='List variants and basic statistics')
    parser.add_argument('--lint', action='store_true', help='Run variant health/lint checks')
    parser.add_argument('--pcb-sync', nargs='?', const='<All variants>', metavar='VARIANT', help='Audit schematic ↔ PCB variant sync; omit VARIANT to check all')
    parser.add_argument('--compare', nargs=2, metavar=('LEFT', 'RIGHT'), help='Compare two variants; use <Default> for base')
    parser.add_argument('--promote', metavar='VARIANT', help='Make named variant Default')
    parser.add_argument('--keep-source', action='store_true', help='With --promote, keep the source as a named equivalent variant')
    parser.add_argument('--swap-default', nargs=2, metavar=('VARIANT', 'OLD_DEFAULT_NAME'), help='Make VARIANT Default and preserve old Default')
    parser.add_argument('--rename', nargs=2, metavar=('OLD', 'NEW'), help='Rename a variant')
    parser.add_argument('--duplicate', nargs=2, metavar=('SOURCE', 'NEW'), help='Duplicate a variant; SOURCE may be <Default>')
    parser.add_argument('--delete', metavar='VARIANT', help='Delete a named variant')
    parser.add_argument('--clean', action='store_true', help='Remove redundant overrides while preserving semantics')
    parser.add_argument('--preview', action='store_true', help='Print plan and do not write')
    parser.add_argument('--yes', action='store_true', help='Apply without interactive confirmation (CLI only)')
    parser.add_argument('--csv', help='For --compare, write detailed comparison CSV')
    parser.add_argument('--plugin-mode', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--launch-note', default='', help=argparse.SUPPRESS)
    parser.add_argument('--version', action='version', version=APP_VERSION)
    args = parser.parse_args(argv)

    if not args.schematic:
        return run_gui(plugin_mode=args.plugin_mode, launch_note=args.launch_note)
    root = Path(args.schematic).expanduser().resolve()

    try:
        if args.list:
            a = analyze_project(root)
            print(f'Project: {a.project_file or "(no .kicad_pro)"}')
            print(f'Schematics: {a.schematic_count}; symbol instances: {a.symbol_instances}; sheet instances: {a.sheet_instances}')
            for st in a.stats:
                print(
                    f'{st.name}: changed={st.differing_instances}, DNP={st.dnp_instances}, '
                    f'BOM-excluded={st.bom_excluded_instances}, ValueΔ={st.value_differences}, '
                    f'FootprintΔ={st.footprint_differences}, FieldΔ={st.field_differences}, FlagΔ={st.flag_differences}'
                )
            return 0
        if args.lint:
            issues = lint_project(root)
            status,e,w,i = health_summary(issues)
            for issue in issues:
                where = ' / '.join(x for x in (issue.file, issue.item, issue.variant) if x)
                print(f'{issue.severity}: {issue.code}: {where}: {issue.message}')
            print(f'{status}: {e} error / {w} warning / {i} info')
            return 2 if e else (1 if w else 0)
        if args.pcb_sync is not None:
            selected = None if args.pcb_sync == '<All variants>' else args.pcb_sync
            board, issues = audit_pcb_sync(root, selected)
            print(f'Board: {board or "(not found)"}')
            for issue in issues:
                print(f'{issue.severity}: {issue.reference or "-"}: {issue.variant or "-"}: {issue.property}: {issue.schematic!r} -> {issue.pcb!r}: {issue.message}')
            status,e,w,i = sync_summary(issues)
            print(f'{status}: {e} error / {w} warning / {i} info')
            return 2 if e else (1 if w else 0)
        if args.compare:
            records = compare_variants(root, args.compare[0], args.compare[1])
            for r in records:
                print(f'{r.file}: {r.item}: {r.property}: {r.before!r} -> {r.after!r}')
            print(f'{len(records)} differing properties.')
            if args.csv:
                export_changes_csv(records, Path(args.csv))
            return 0

        plan: Optional[VariantPlan] = None
        if args.promote:
            plan = plan_promote_variant(root, args.promote, args.keep_source)
        elif args.swap_default:
            plan = plan_swap_default(root, args.swap_default[0], args.swap_default[1])
        elif args.rename:
            plan = plan_rename_variant(root, args.rename[0], args.rename[1])
        elif args.duplicate:
            plan = plan_duplicate_variant(root, args.duplicate[0], args.duplicate[1])
        elif args.delete:
            plan = plan_delete_variant(root, args.delete)
        elif args.clean:
            plan = plan_clean_overrides(root)
        else:
            return run_gui(str(root), plugin_mode=args.plugin_mode, launch_note=args.launch_note)

        for line in plan.summary:
            print(line)
        print(f'Files to rewrite: {len(plan.schematic_files) + (1 if plan.project_new_text is not None else 0)}')
        if args.preview:
            return 0
        if not args.yes:
            ans = input('Apply this plan? Type YES: ')
            if ans != 'YES':
                print('Cancelled.')
                return 1
        backups = apply_plan(plan)
        print('Applied. Backups:')
        for b in backups:
            print(' ', b)
        return 0
    except VariantPromoterError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
