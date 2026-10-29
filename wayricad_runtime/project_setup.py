"""Versioned simulation input files, separate from immutable result records."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .project_results import _canonical, _decode, _hash_file, _linked, MAX_BYTES

SCHEMA = 'wayricad.project-setup/v1'
PLUGINS = {'quick-pi', 'quick-si', 'quick-therm', 'quick-emerge'}


class SourceChangedError(ValueError):
    """An input file needs explicit review against a different board revision."""


def make_setup(plugin, board_path, state):
    """Capture JSON inputs and the saved board revision without changing either."""
    board = Path(board_path).resolve()
    if plugin not in PLUGINS or not isinstance(state, dict):
        raise ValueError('Choose a supported quick tool and an input object.')
    if not board.is_file():
        raise ValueError('Save the PCB before saving a simulation setup.')
    result = dict(schema=SCHEMA, plugin=plugin, source=dict(board_name=board.name,
                  source_sha256=_hash_file(board)), state=state)
    return _decode(_canonical(result))


def save_setup(path, record, *, protected_sources=()):
    """Atomically write an explicitly chosen file; never overwrite a design."""
    target = Path(path).absolute()
    if target.suffix.lower() != '.json' or not target.parent.is_dir() or _linked(target):
        raise ValueError('Choose a JSON setup file in an existing directory.')
    for source in protected_sources:
        source = Path(source)
        if (target.resolve() == source.resolve() or
                target.exists() and source.exists() and os.path.samefile(target, source)):
            raise ValueError('Setup data must not overwrite the source board or project files.')
    raw = _canonical(record)
    descriptor, name = tempfile.mkstemp(prefix='.setup-', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return str(target.resolve())


def load_setup(path, plugin, board_path, *, validate_state=None, allow_changed_source=False):
    """Validate the whole input object before UI mutation; old results are excluded."""
    with Path(path).open('rb') as stream:
        record = _decode(stream.read(MAX_BYTES + 1))
    if (set(record) != {'schema', 'plugin', 'source', 'state'} or
            record.get('schema') != SCHEMA or record.get('plugin') != plugin or plugin not in PLUGINS):
        raise ValueError('This is not a compatible '+plugin+' setup file. Select setup data, not a report or result file.')
    source = record.get('source')
    if (not isinstance(source, dict) or set(source) != {'board_name', 'source_sha256'} or
            not isinstance(source.get('board_name'), str) or
            not isinstance(source.get('source_sha256'), str) or len(source['source_sha256']) != 64 or
            any(c not in '0123456789abcdef' for c in source['source_sha256']) or
            not isinstance(record.get('state'), dict)):
        raise ValueError('The setup source or input object is invalid.')
    board = Path(board_path).resolve()
    changed = not board.is_file() or _hash_file(board) != source['source_sha256']
    if changed and not allow_changed_source:
        raise SourceChangedError('The setup was saved for another PCB revision. Review its nets, pads and model assignments before using it here.')
    state = record['state']
    if validate_state is not None:
        state = validate_state(state)
    return dict(record, state=state, source_changed=changed)
