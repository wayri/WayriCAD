"""Read-only source classification and bounded, content-keyed schematic reads.

Cached syntax is copied before use. Every access reads and hashes current bytes;
the cache never stores native validation or preview/apply acceptance results.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import copy
import hashlib
import json
import threading
from types import SimpleNamespace

from . import sexpr as sx
from .model import MergeError
from .schematic import expand_path

_parsed = OrderedDict()
_lock = threading.RLock()
_MAX_BYTES = 16 * 1024 * 1024
_MAX_FILES = 32


def read_schematic(path, hashes=None):
    """Return independent syntax for current saved bytes, keyed by SHA-256."""
    path = Path(path).resolve()
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if hashes is not None:
        hashes[str(path)] = digest
    key = (str(path), digest)
    with _lock:
        entry = _parsed.get(key)
        if entry is None:
            tree = sx.loads(data.decode('utf-8-sig'))
            if len(data) <= _MAX_BYTES:
                # Retain only the latest revision of each path.
                for old in [old for old in _parsed if old[0] == str(path)]:
                    del _parsed[old]
                _parsed[key] = (len(data), tree)
                while len(_parsed) > _MAX_FILES or sum(item[0] for item in _parsed.values()) > _MAX_BYTES:
                    _parsed.popitem(last=False)
            return copy.deepcopy(tree)
        _parsed.move_to_end(key)
        return copy.deepcopy(entry[1])


@dataclass(frozen=True)
class DetectedSource:
    """A source choice; repeated occurrences remain explicit UUID selections."""
    selected_file: str
    project: str
    kind: str
    sheet_paths: tuple[str, ...] = ()
    has_layout: bool = False

    @property
    def selection(self):
        return {'whole_project': self.kind != 'sheet', 'sheet_paths': list(self.sheet_paths),
                'max_depth': None, 'include_layout': self.has_layout, 'region_mm': None}


def _occurrences(root, wanted):
    results = []
    count = 0
    parsed = {}
    def visit(path, occurrence, ancestors):
        nonlocal count
        count += 1
        if count > 512 or len(ancestors) >= 32 or path in ancestors:
            raise MergeError('Cyclic or excessively large source hierarchy.')
        if path not in parsed:parsed[path]=read_schematic(path)
        tree = parsed[path]
        if sx.tag(tree) != 'kicad_sch':
            raise MergeError('Source is not a modern KiCad schematic.')
        occurrence = occurrence or '/' + sx.value(tree, 'uuid')
        if path == wanted:
            results.append(occurrence)
        for sheet in sx.children(tree, 'sheet'):
            raw = sx.propval(sheet, 'Sheetfile') or sx.propval(sheet, 'Sheet file')
            child = expand_path(raw, root.parent, path.parent)
            visit(child, occurrence + '/' + sx.value(sheet, 'uuid'), ancestors + [path])
    visit(root, '', [])
    return tuple(results)


def sheet_catalogue(spec):
    """List scope choices without allocating import UUIDs or applying variants.

    This is saved hierarchy metadata only. Discovery/native validation still
    verifies symbol identities, annotation and electrical behavior before import.
    """
    from .paths import resolve_asset
    project=Path(spec.project).resolve().with_suffix('.kicad_pro')
    source=SimpleNamespace(spec=spec,project_file=project,
                           project=json.loads(project.read_text(encoding='utf-8-sig')) if project.is_file() else {})
    root=project.with_suffix('.kicad_sch');items=[];parsed={}
    def visit(path,occurrence,display,ancestors):
        if len(items)>=512 or len(ancestors)>=32 or path in ancestors:
            raise MergeError('Cyclic or excessively large source hierarchy.')
        if path not in parsed:parsed[path]=read_schematic(path)
        tree=parsed[path]
        if sx.tag(tree)!='kicad_sch':raise MergeError('Invalid source schematic.')
        occurrence=occurrence or '/'+sx.value(tree,'uuid')
        item={'sheet_path':occurrence,'display_path':display,'file':str(path),
              'symbols':len(sx.children(tree,'symbol')),'descendant_symbols':len(sx.children(tree,'symbol'))}
        items.append(item)
        for node in sx.children(tree,'sheet'):
            raw=sx.propval(node,'Sheetfile') or sx.propval(node,'Sheet file')
            child=resolve_asset(raw,source,path.parent)
            if child is None or not child.is_file():raise MergeError('Cannot resolve child schematic '+raw+'. Configure source path overrides.')
            name=sx.propval(node,'Sheetname') or sx.propval(node,'Sheet name') or child.stem
            count=visit(child,occurrence+'/'+sx.value(node,'uuid'),display+name+'/',ancestors+[path])
            item['descendant_symbols']+=count
        return item['descendant_symbols']
    visit(root,'','/'+spec.alias+'/',[])
    return items[1:]


def detect_source(path):
    """Classify a file; return all owning projects instead of guessing ambiguity.

    Child ownership is searched in the selected directory and four ancestors,
    with at most 64 project roots. No recursive whole-disk scan is performed.
    Unresolved external/path-variable hierarchies require explicit root selection.
    """
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {'.kicad_pro', '.kicad_sch', '.kicad_pcb'}:
        raise MergeError('Select a saved KiCad project, schematic or PCB.')
    pro, sch, pcb = (path.with_suffix(ext) for ext in ('.kicad_pro', '.kicad_sch', '.kicad_pcb'))
    if pro.is_file() and sch.is_file():
        kind = 'project' if pcb.is_file() else 'schematic'
        return [DetectedSource(str(path), str(pro), kind, has_layout=pcb.is_file())]
    if path.suffix.lower() == '.kicad_pcb':
        return [DetectedSource(str(path), str(path), 'layout', has_layout=True)]
    if path.suffix.lower() == '.kicad_pro':
        raise MergeError('Selected project has no basename-matched root schematic.')
    owners = []
    candidates = set()
    for directory in [path.parent, *list(path.parent.parents)[:4]]:
        candidates.update(directory.glob('*.kicad_pro'))
        if len(candidates) > 64:
            raise MergeError('Too many possible owning projects; select the root project explicitly.')
    for candidate in sorted(candidates):
        root = candidate.with_suffix('.kicad_sch')
        if not root.is_file():
            continue
        try:
            occurrences = _occurrences(root.resolve(), path)
        except (MergeError, OSError, ValueError):
            continue
        if occurrences:
            owners.append(DetectedSource(str(path), str(candidate), 'sheet', occurrences,
                                         candidate.with_suffix('.kicad_pcb').is_file()))
    return owners or [DetectedSource(str(path), str(path), 'schematic')]


def choose_source(parent, path):
    """Present only ambiguous owner/occurrence choices; return the resolved pick."""
    import wx
    choices = detect_source(path)
    if len(choices) > 1:
        with wx.SingleChoiceDialog(parent, 'This sheet belongs to several projects. Choose its owner.',
                                   'Source project', [item.project for item in choices]) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            choice = choices[dialog.GetSelection()]
    else:
        choice = choices[0]
    if choice.kind == 'sheet' and len(choice.sheet_paths) > 1:
        with wx.SingleChoiceDialog(parent, 'This sheet occurs more than once. Choose the exact occurrence.',
                                   'Sheet occurrence', list(choice.sheet_paths)) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            choice = DetectedSource(choice.selected_file, choice.project, 'sheet',
                                    (choice.sheet_paths[dialog.GetSelection()],), choice.has_layout)
    return choice
