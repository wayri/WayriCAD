"""Byte-exact 3D model embedding with transform-preserving text patches."""
from __future__ import annotations
from dataclasses import dataclass
import gzip
from pathlib import Path
import re
from typing import Callable
from .codec import Codec, MAX_BYTES, sha256
from .paths import Resolver
from .sexpr import Atom, FormatError, Node, parse, patch, quote, semantic

PREFIX = 'kicad-embed://'
MAX_JOB_BYTES = 512*1024*1024

@dataclass
class Embedded:
    name: str
    checksum: str
    encoded: str
    raw: str


def embedded_entries(text: str, root: Node | None = None) -> dict[str, Embedded]:
    root = root or parse(text)
    block = root.one(text, 'embedded_files')
    result = {}
    if block:
        for node in block.nodes(text, 'file'):
            name_node = node.one(text, 'name')
            if not name_node:
                raise FormatError('Embedded entry lacks a name')
            name = name_node.arg().value(text)
            if name in result:
                raise FormatError('Duplicate embedded file name: ' + name)
            checksum_node, data_node = node.one(text, 'checksum'), node.one(text, 'data')
            checksum = checksum_node.arg().value(text) if checksum_node else ''
            encoded = ''
            if data_node and len(data_node.children) > 1:
                token = data_node.arg()
                encoded = token.value(text).strip('|')
                encoded = ''.join(encoded.split())
            result[name] = Embedded(name, checksum, encoded, node.raw(text))
    return result


def make_entry(name: str, encoded: str, digest: str, newline='\n', file_type='model') -> str:
    if file_type not in ('model', 'other'):
        raise ValueError('Unsupported embedded file type')
    wrapped = newline.join(encoded[i:i+76] for i in range(0, len(encoded), 76))
    return '(file (name %s) (type %s) (data%s|%s|%s) (checksum %s))' % (
        quote(name), file_type, newline, wrapped, newline, quote(digest))


def dependency_warning(path: Path, data: bytes) -> str:
    suffix = path.suffix.lower()
    if suffix in ('.wrz', '.gz'):
        try:
            # A bounded read avoids a decompression bomb in an untrusted model.
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                raw = stream.read(MAX_BYTES+1)
            if len(raw) > MAX_BYTES:
                return 'Compressed model exceeds dependency-inspection limit'
            data = raw
        except (OSError, EOFError):
            return 'Compressed model could not be inspected for external dependencies'
    if suffix in ('.wrl', '.wrz', '.x3d', '.gz'):
        text = data.decode('utf-8', errors='replace')
        # Conservatively refuse models that fetch external textures/Inline content.
        if re.search(r'\burl\s*(?:\[\s*)?["\']', text, re.I) or re.search(r'\burl\s*=', text, re.I):
            return 'Model contains URL/texture/Inline dependencies; flatten it before embedding'
    return ''


@dataclass
class ModelRow:
    index: int
    reference: str
    settings: str
    status: str = 'Not scanned'
    detail: str = ''
    resolved: Path | None = None
    size: int = 0
    digest: str = ''
    target: str = ''
    checked: bool = False
    payload: Embedded | None = None
    source_stamp: tuple | None = None

    @property
    def ready(self):
        return self.status in ('Ready', 'Localize embedded')

@dataclass
class Plan:
    name: str
    original: str
    source_dir: Path | None
    rows: list[ModelRow]
    existing: dict[str, Embedded]
    source_path: Path | None = None
    owner: object = None

    @property
    def actionable(self):
        return [r for r in self.rows if r.checked and r.ready]

    def build(self) -> str:
        chosen = self.actionable
        if not chosen:
            return self.original
        root = parse(self.original)
        models = root.nodes(self.original, 'model')
        changes, new_entries = [], {}
        for row in chosen:
            assert row.payload is not None
            atom = models[row.index].arg()
            changes.append((atom.start, atom.end, quote(PREFIX+row.target)))
            existing = self.existing.get(row.target)
            if existing and existing.encoded:
                if existing.encoded != row.payload.encoded:
                    raise FormatError('Embedded name collision: '+row.target)
            else:
                new_entries[row.target] = row.payload.raw
                if existing and sum(1 for r in chosen if r.target == row.target and r.index < row.index) == 0:
                    old_block = root.one(self.original, 'embedded_files')
                    for node in old_block.nodes(self.original, 'file'):
                        if node.one(self.original, 'name').arg().value(self.original) == row.target:
                            changes.append((node.start, node.end, ''))
        newline = '\r\n' if '\r\n' in self.original else '\n'
        if new_entries:
            block = root.one(self.original, 'embedded_files')
            body = newline.join(new_entries.values())
            if block:
                changes.append((block.end-1, block.end-1, newline+body+newline))
            else:
                changes.append((root.end-1, root.end-1, newline+'\t(embedded_files'+newline+body+newline+'\t)'+newline))
        output = patch(self.original, changes)
        # Prove every non-embedding token, including every model setting, survived.
        if semantic(output, True) != semantic(self.original, True):
            raise FormatError('Safety check: an unrelated footprint setting changed')
        output_root = parse(output)
        new_models = output_root.nodes(output, 'model')
        for before, after in zip(models, new_models):
            if self.original[before.arg().end:before.end] != output[after.arg().end:after.end]:
                raise FormatError('Safety check: model settings changed')
        return output

    def manifest(self):
        return {'name': self.name, 'source': str(self.source_path or ''),
                'models': [{'index': r.index, 'original_reference': r.reference,
                            'embedded_reference': PREFIX+r.target if r.checked and r.ready else r.reference,
                            'source_sha256': r.digest, 'size': r.size, 'status': r.status,
                            'embedded': bool(r.checked and r.ready), 'settings_original': r.settings,
                            'resolved_source': str(r.resolved or ''), 'detail': r.detail} for r in self.rows]}


class Planner:
    def __init__(self, resolver: Resolver, codec: Codec | None = None):
        self.resolver = resolver
        self.codec = codec or Codec()
        self.cache = {}
        self.total_bytes = 0

    def payload(self, path: Path):
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        if key in self.cache:
            return self.cache[key]
        if stat.st_size <= 0 or stat.st_size > MAX_BYTES:
            raise ValueError('Model is empty or exceeds the 256 MiB safety limit')
        if self.total_bytes+stat.st_size > MAX_JOB_BYTES:
            raise ValueError('Selection exceeds 512 MiB safety budget; process a smaller batch')
        with path.open('rb') as stream:
            import os
            before = os.fstat(stream.fileno())
            data = stream.read(MAX_BYTES+1)
            after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(data) != before.st_size:
            raise ValueError('Model changed while being read; scan again')
        warning = dependency_warning(path, data)
        if warning:
            raise ValueError(warning)
        digest = sha256(data)
        encoded = self.codec.encode(data)
        # Full content hash avoids basename conflicts even across footprint instances.
        suffix = path.suffix
        if suffix.lower() in ('.gz', '.bz2', '.xz', '.zip') and len(path.suffixes) > 1:
            suffix = ''.join(path.suffixes[-2:])
        basename = path.name[:-len(suffix)] if suffix else path.name
        stem = re.sub(r'[^A-Za-z0-9_-]+', '_', basename)[:24] or 'model'
        name = stem+'__'+digest+suffix.lower()
        entry = Embedded(name, digest, encoded, make_entry(name, encoded, digest))
        result = entry, len(data), (before.st_size, before.st_mtime_ns)
        self.cache[key] = result
        self.total_bytes += len(data)
        return result

    def scan(self, text: str, name: str = '', source_dir: Path | None = None,
             pool: dict[str, Embedded] | None = None, overrides: dict[int, str] | None = None,
             cancelled: Callable[[], bool] = lambda: False) -> Plan:
        root = parse(text)
        if root.head(text) != 'footprint':
            raise FormatError('Expected a modern .kicad_mod footprint')
        existing = embedded_entries(text, root)
        rows = []
        for index, model in enumerate(root.nodes(text, 'model')):
            if cancelled():
                raise InterruptedError('Scan cancelled')
            atom = model.arg()
            reference = atom.value(text)
            row = ModelRow(index, reference, text[atom.end:model.end])
            rows.append(row)
            try:
                if reference.startswith(PREFIX) and not (overrides and index in overrides):
                    embedded_name = reference[len(PREFIX):]
                    own = existing.get(embedded_name)
                    inherited = (pool or {}).get(embedded_name)
                    if own and own.encoded:
                        row.status, row.detail = 'Embedded', 'Payload already belongs to this footprint'
                    elif inherited and inherited.encoded:
                        row.status, row.detail = 'Localize embedded', 'Copy board-level payload into the footprint'
                        row.payload, row.target = inherited, embedded_name
                        row.checked = True
                    else:
                        row.status, row.detail = 'Missing payload', 'Embedded reference has no available model bytes'
                    continue
                path = Path(overrides[index]).resolve() if overrides and index in overrides else self.resolver.resolve(reference, source_dir)
                entry, size, stamp = self.payload(path)
                source_digest = entry.checksum
                other = existing.get(entry.name)
                if other and other.encoded and other.encoded != entry.encoded:
                    # A different compressor may create a different stream for identical bytes.
                    if self.codec.decode(other.encoded) != self.codec.decode(entry.encoded):
                        raise ValueError('An existing embedded file conflicts with this content-derived name')
                    entry = other
                row.resolved, row.payload, row.target = path, entry, entry.name
                row.size, row.digest, row.source_stamp = size, source_digest, stamp
                row.status, row.checked = 'Ready', True
                row.detail = 'Original bytes; scale, rotation, offset, opacity and visibility unchanged'
            except (OSError, ValueError) as exc:
                row.status, row.detail = 'Needs attention', str(exc)
        return Plan(name or root.arg().value(text), text, source_dir, rows, existing)


def verify_sources(plans: list[Plan]):
    seen = {}
    for plan in plans:
        if plan.source_path and plan.source_path.read_bytes() != plan.original.encode('utf-8'):
            raise ValueError('Footprint changed since preview: '+str(plan.source_path))
        for row in plan.actionable:
            if row.resolved:
                if row.resolved in seen:
                    if seen[row.resolved] != row.digest:
                        raise ValueError('Conflicting scan snapshots for model: '+str(row.resolved))
                    continue
                with row.resolved.open('rb') as stream:
                    current = stream.read(MAX_BYTES+1)
                digest = sha256(current)
                if len(current) > MAX_BYTES or digest != row.digest:
                    raise ValueError('3D model changed since preview: '+str(row.resolved))
                seen[row.resolved] = digest
