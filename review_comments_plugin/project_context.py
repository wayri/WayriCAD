"""Bounded saved-worktree evidence for provider-read review annotations.

Only explicitly referenced paths and a BOM loader's bounded source hierarchy
are read. ``complete`` covers ``knownPaths``, not a recursive repository scan.
HEAD is read before and after; observed hashes describe working-tree bytes,
never an assertion that those bytes have been committed. No files are written.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from wayricad_runtime.schematic_sexpr import parse

from .bom_review import load_bom
from .context_status import _identity
from .model import anchor
from .review_targets import relative_path


MAX_FILES = 128
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ANNOTATIONS = 5001


def _git(root, arguments):
    result = subprocess.run(['git', '--no-replace-objects', *arguments], cwd=root,
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                            check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout


def _signature(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _probe(root, relative):
    """Return a stable path chain or an explicit ENOENT parent witness."""
    relative_path(relative)
    current = root
    chain = []
    for index, part in enumerate(('', *Path(relative).parts)):
        if part:
            current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if not chain:
                raise ValueError('The project root disappeared.') from None
            # Verify that the parent was unchanged while its child was probed.
            if _signature(current.parent.lstat()) != chain[-1]:
                raise ValueError('A context directory changed during observation.')
            return None, ('missing', tuple(chain), current.relative_to(root).as_posix())
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Context paths cannot use links or reparse points.')
        if index < len(Path(relative).parts) and not stat.S_ISDIR(info.st_mode):
            raise ValueError('A context parent is not a directory.')
        chain.append(_signature(info))
    if not stat.S_ISREG(info.st_mode) or current.resolve(strict=True) != current:
        raise ValueError('A context file is not a contained regular file.')
    return current, ('file', tuple(chain))


def _read(root, relative):
    path, witness = _probe(root, relative)
    if path is None:
        return None, witness
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Context file exceeds its bounded read limit.')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        before = _signature(os.fstat(stream.fileno()))
        if before != witness[1][-1]:
            raise ValueError('Context source changed before reading.')
        data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES or _signature(os.fstat(stream.fileno())) != before:
            raise ValueError('Context source changed while reading.')
    if _probe(root, relative)[1] != witness:
        raise ValueError('Context path changed while reading.')
    return data, witness


def _record(name, data):
    result = dict(sha256=hashlib.sha256(data).hexdigest())
    if Path(name).suffix.lower() in ('.kicad_pcb', '.kicad_sch'):
        tree = parse(data.decode('utf-8-sig'))
        if tree.tag != Path(name).suffix.lower()[1:]:
            raise ValueError('Context source has the wrong native document type.')
        pending, identifiers = [tree], []
        while pending:
            node = pending.pop()
            if node.tag in ('uuid', 'tstamp'):
                value = node.val()
                if value:
                    identifiers.append(value)
            pending.extend(node.children)
        result['objectIds'] = sorted(identifiers)
    return result


def build_inventory(root, current_scope, annotations):
    """Return current evidence plus ``originalInventories`` keyed by commit.

    Failures produce ``verified=False, complete=False`` with a generic warning.
    Callers must not interpret such a result, missing baseline, or omitted
    identity collection as proof of deletion. Unknown/symlinked paths are not
    followed. All annotation paths must belong to the configured project.
    """
    result = dict(scope=dict(current_scope) if isinstance(current_scope, dict) else {}, verified=False, complete=False,
                  files={}, knownPaths=[], originalInventories={}, provenance='working-tree')
    try:
        expected = _identity(current_scope)
        if not isinstance(annotations, (list, tuple)) or len(annotations) > MAX_ANNOTATIONS:
            raise ValueError('Context annotations exceed their bounded limit.')
        given = Path(root).expanduser().absolute()
        if given.is_symlink():
            raise ValueError('Context root must not be a link.')
        base = given.resolve(strict=True)
        if Path(_git(base, ['rev-parse', '--show-toplevel']).decode().strip()).resolve() != base:
            raise ValueError('Context root must be the selected Git worktree root.')
        head = _git(base, ['rev-parse', '--verify', 'HEAD^{commit}']).decode('ascii').strip()
        selected = _identity(dict(current_scope, ref=head))
        result['scope'] = selected
        targets, names, bom_origins, baseline_paths = [], set(), set(), set()
        names.add(relative_path(current_scope['file']))
        for annotation in annotations:
            target = anchor(annotation['anchor'])
            identity = _identity(target)
            if any(identity[key] != expected[key] for key in ('provider', 'host', 'repository')):
                raise ValueError('Context inventory cannot include a foreign project.')
            targets.append(target)
            names.add(target['file'])
            context = target.get('context', {})
            if context.get('type') == 'gerber':
                names.add(context['file'])
            elif context.get('type') == 'bom':
                names.update(context['sourceFiles'])
                bom_origins.add(target['file'])
            else:
                baseline_paths.add((target['ref'], target['file']))
            if target.get('variant') not in (None, '*'):
                bom_origins.add(target['file'])
        for name in bom_origins:
            names.add(Path(name).with_suffix('.kicad_pro').as_posix())
        if len(names) > MAX_FILES or len(baseline_paths) > MAX_FILES:
            raise ValueError('Context source catalog exceeds its bounded limit.')
        observed, witnesses, total = {}, {}, 0

        def capture(name):
            nonlocal total
            if name in observed:
                return
            if len(observed) >= MAX_FILES:
                raise ValueError('Context source catalog exceeds its bounded limit.')
            data, witness = _read(base, name)
            total += len(data) if data is not None else 0
            if total > MAX_BYTES:
                raise ValueError('Context source catalog exceeds its byte limit.')
            observed[name], witnesses[name] = data, witness
            if data is not None:
                result['files'][name] = _record(name, data)

        for name in sorted(names):
            capture(name)
        for name in sorted(bom_origins):
            if observed[name] is None:
                continue
            # Missing explicitly linked BOM sources are proven absence, not a
            # parser failure. Keep BOM completeness unknown until all exist.
            linked = {source for target in targets if target['file'] == name
                      for source in target.get('context', {}).get('sourceFiles', {})}
            if any(observed.get(source) is None for source in linked):
                continue
            snapshot = load_bom(base / name, base)
            for source, digest in snapshot['source_hashes'].items():
                capture(source)
                if result['files'].get(source, {}).get('sha256') != digest:
                    raise ValueError('BOM evidence changed during observation.')
            record = result['files'][name]
            record['objectIds'] += [row['id'] for row in snapshot['rows']]
            record['objectIds'].sort()
            record['fieldsByObject'] = {row['id']: sorted(row['fields']) for row in snapshot['rows']}
            record['bomComplete'] = True
            record['variants'] = list(snapshot['variants'])
        for revision, name in sorted(baseline_paths):
            specification = revision + ':' + name
            size = int(_git(base, ['cat-file', '-s', specification]).decode('ascii').strip())
            if size < 0 or size > MAX_FILE_BYTES or total + size > MAX_BYTES:
                raise ValueError('Original context source exceeds its bounded limit.')
            data = _git(base, ['show', specification])
            if len(data) != size:
                raise ValueError('Original context source changed during observation.')
            total += size
            previous = result['originalInventories'].setdefault(revision, dict(
                scope=dict(selected, ref=revision), verified=True, complete=True,
                files={}, knownPaths=[], provenance='git-commit'))
            previous['files'][name] = dict(sha256=hashlib.sha256(data).hexdigest())
            previous['knownPaths'].append(name)
        # Reobserve exact paths, including every absent child's stable parent.
        for name, data in observed.items():
            again, witness = _read(base, name)
            if witness != witnesses[name] or again != data:
                raise ValueError('Context inventory changed during observation.')
        if _git(base, ['rev-parse', '--verify', 'HEAD^{commit}']).decode('ascii').strip() != head:
            raise ValueError('The selected Git revision changed during observation.')
        result.update(verified=True, complete=True, knownPaths=sorted(observed))
        result['observationId'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, subprocess.SubprocessError):
        result.update(verified=False, complete=False,
                      warning='Context inventory is unavailable or changed during observation; no deletion is established.')
    return result
