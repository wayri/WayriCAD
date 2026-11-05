"""Bounded, read-only saved KiCad document catalog for the Review web canvas."""
from __future__ import annotations

import hashlib
from pathlib import Path

from wayricad_runtime.schematic_sexpr import parse, properties

from .canvas_render import _sources


MAX_DOCUMENTS = 64
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_KINDS = {'.kicad_pcb': 'pcb', '.kicad_sch': 'schematic'}


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _no_links(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError('Review documents must stay inside the selected directory.') from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Review documents cannot use linked files or directories.')


def _schematic_files(path: Path, root: Path) -> set[Path]:
    # Preflight file sizes and symlink aliases before the shared parser's
    # transitive read. Its result then confirms this explicit source list.
    result = set()
    pending = [path]
    total = 0
    project = path.with_suffix('.kicad_pro')
    if project.exists() or project.is_symlink():
        _no_links(root, project)
    while pending:
        current = pending.pop()
        if current in result:
            continue
        _no_links(root, current)
        if not current.is_file():
            raise ValueError('A schematic child sheet is missing.')
        total += current.stat().st_size
        if total > MAX_SOURCE_BYTES or len(result) >= MAX_DOCUMENTS:
            raise ValueError('Schematic hierarchy exceeds the bounded Review catalog.')
        result.add(current)
        data = current.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError('A schematic child sheet exceeds the bounded Review catalog.')
        tree = parse(data.decode('utf-8-sig'))
        for sheet in tree.nodes('sheet'):
            props = properties(sheet)
            filename = props.get('Sheetfile', props.get('Sheet file', ('',)))[0]
            raw = current.parent / filename
            if not raw.resolve().is_relative_to(root):
                raise ValueError('A schematic child sheet is outside the selected directory.')
            _no_links(root, raw)
            child = raw.resolve()
            if child.suffix.lower() != '.kicad_sch':
                raise ValueError('A schematic child has an unsupported file type.')
            pending.append(child)
    sources = _sources(path, 'schematic')
    if result != {item for item in sources if item.suffix.lower() == '.kicad_sch'}:
        raise ValueError('Schematic hierarchy changed while building the Review catalog.')
    return result


class ReviewDocuments:
    """Catalog exact saved files; session/write guards remain with ReviewSession."""

    def __init__(self, path: str | Path):
        given = Path(path).expanduser().absolute()
        if (given.is_symlink() or given.parent.is_symlink() or
                given.suffix.lower() not in _KINDS or not given.is_file()):
            raise ValueError('Choose a saved KiCad PCB or schematic file.')
        self.root = given.parent.resolve()
        selected = given.resolve()
        # Ancestors above the explicitly selected directory can be OS aliases
        # (macOS /var -> /private/var). Bind to the canonical selected root;
        # links within that root remain forbidden on every subsequent read.
        _no_links(self.root, selected)
        paths = {selected}
        pair_suffix = '.kicad_sch' if selected.suffix.lower() == '.kicad_pcb' else '.kicad_pcb'
        pair = selected.with_suffix(pair_suffix)
        if pair.exists() or pair.is_symlink():
            _no_links(self.root, pair)
            if not pair.is_file():
                raise ValueError('The paired KiCad document is not a regular file.')
            paths.add(pair)
        for document in tuple(paths):
            if document.suffix.lower() == '.kicad_sch':
                paths.update(_schematic_files(document, self.root))
        if len(paths) > MAX_DOCUMENTS:
            raise ValueError('Review document catalog exceeds 64 saved files.')
        total = 0
        for document in paths:
            _no_links(self.root, document)
            if not document.is_file():
                raise ValueError('A saved Review document is missing.')
            total += document.stat().st_size
            if total > MAX_SOURCE_BYTES:
                raise ValueError('Saved Review documents exceed the 64 MiB catalog limit.')
        self.documents = {item.relative_to(self.root).as_posix(): item for item in
                          sorted(paths, key=lambda item: item.relative_to(self.root).as_posix())}
        self.selected_id = selected.relative_to(self.root).as_posix()

    def entries(self) -> list[dict[str, str]]:
        return [{'id': name, 'label': name, 'kind': _KINDS.get(path.suffix.lower(), 'manufacturing')}
                for name, path in self.documents.items()]

    def add_gerber(self, path):
        from .project_artifacts import read_artifact
        raw = Path(path).absolute()
        payload = read_artifact(self.root, raw)
        if len(self.documents) >= MAX_DOCUMENTS and payload['path'] not in self.documents:
            raise ValueError('Saved Review catalog exceeds 64 files.')
        self.documents[payload['path']] = raw
        return payload['path']

    def path_for(self, document_id: str) -> Path:
        if not isinstance(document_id, str) or document_id not in self.documents:
            raise ValueError('This Review document ID is not registered.')
        path = self.documents[document_id]
        _no_links(self.root, self.root / Path(document_id))
        if not path.is_file() or path.resolve() != self.root / Path(document_id):
            raise ValueError('The saved Review document moved or became linked.')
        return path

    def assert_current(self, document_id: str, digest: str) -> None:
        path = self.path_for(document_id)
        if not isinstance(digest, str) or _sha(path) != digest:
            raise ValueError('Saved Review document changed. Reload it before continuing.')

    def load(self, document_id: str) -> dict:
        path = self.path_for(document_id)
        if path.suffix.lower() not in _KINDS:
            from .project_artifacts import read_artifact
            payload = read_artifact(self.root, path)
            return dict(payload, documents=self.entries(), current_document_id=document_id)
        before = _sha(path)
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('Saved Review document exceeds the 64 MiB read limit.')
        data = path.read_bytes()
        if len(data) > MAX_SOURCE_BYTES or _sha(self.path_for(document_id)) != before:
            raise ValueError('Saved Review document changed during read. Reload it.')
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError as exc:
            raise ValueError('Saved Review document is not UTF-8 KiCad source.') from exc
        return {'source': text, 'path': document_id, 'source_sha256': before,
                'view': _KINDS[path.suffix.lower()], 'documents': self.entries(),
                'current_document_id': document_id}
