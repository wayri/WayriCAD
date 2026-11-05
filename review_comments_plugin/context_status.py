"""Read-only context classification from explicit immutable-revision inventories.

``classify_context(anchor, inventory)`` never reads a file or calls a provider.
The caller supplies an inventory with ``scope`` (provider/host/repository/ref),
``verified: True``, ``complete: True``, and a ``files`` mapping. These assertions
mean a successful complete observation associated with that immutable revision,
not a local cache or a failed request interpreted as an empty result. Observed
working-tree bytes must not be represented as commit bytes: provide their actual
hashes and an original commit inventory when comparing legacy anchors. Each file record can contain
``sha256``, ``objectIds``, ``fieldsByObject`` and ``variants``. Present identity
collections must be exhaustive; omitted collections mean unknown, not empty.
Fields are keyed by stable object ID. References are display labels, not IDs.
Project-wide variants can instead be supplied as the inventory's ``variants``.
The ``*`` variant means all variants, not a named variant that can disappear.
Explicit ``provenance`` is either ``working-tree`` or ``git-commit`` and is
retained in classification evidence. A working-tree HEAD identifies its Git
baseline; it does not claim that observed saved bytes match that commit.
For ``anchor.context.type == 'bom'``, use the origin file's record, with
``bomComplete: True`` confirming complete BOM extraction, ``context.rowId`` in
``objectIds``, and its fields in ``fieldsByObject``. ``context.sourceFiles``
hashes identify the BOM inputs. Gerber context selects ``context.file`` and
checks its ``sha256``. Neither context inherits an origin PCB object's UUID.

Missing files require a complete file listing; missing objects/fields/variants
require their respective complete collections. No rename, spatial, reference,
reply-parent or migration-chain inference is performed. The original anchor is
preserved. A status event is only an idempotent proposal, never a provider write.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath
import re

from .model import host, scope


_CONFIRMED = frozenset(('current', 'older-revision', 'changed', 'orphan'))
_SHA256 = re.compile(r'[a-fA-F0-9]{64}\Z')


def _identity(value):
    if not isinstance(value, dict):
        raise ValueError('Context scope must be an object.')
    # Reuse repository/commit validation without limiting inventory file types.
    checked = scope(dict(value, file='context.kicad_pcb'))
    provider = checked.get('provider', 'github')
    origin = (host(value.get('host', 'https://github.com')) if provider == 'github'
              else checked['host'])
    if provider == 'github' and origin != 'https://github.com':
        raise ValueError('GitHub context must use github.com.')
    return dict(provider=provider, host=origin, repository=checked['repository'], ref=checked['ref'])


def _path(value):
    if (not isinstance(value, str) or not value or len(value) > 500 or
            '\\' in value or ':' in value or any(ord(char) < 32 for char in value) or
            PurePosixPath(value).is_absolute() or
            any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError('Context file must be a safe repository-relative path.')
    return value


def _name(value, limit=200):
    if (not isinstance(value, str) or not value or value != value.strip() or
            len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError('Invalid context identity.')
    return value


def _digest(value):
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError('An exact source SHA256 is required.')
    return value.lower()


def _members(value, limit=200):
    # A dict is useful for fields whose values the producer also collected.
    if not isinstance(value, (list, tuple, set, frozenset, dict)):
        raise ValueError('An exhaustive identity collection is required.')
    return [_name(item, limit) for item in value]


def _verified_inventory(value):
    if not isinstance(value, dict) or value.get('verified') is not True or value.get('complete') is not True:
        raise ValueError('A complete verified inventory is required.')
    if 'provenance' in value and value['provenance'] not in ('working-tree', 'git-commit'):
        raise ValueError('Unsupported context inventory provenance.')
    identity = _identity(value.get('scope'))
    files = value.get('files')
    if not isinstance(files, dict):
        raise ValueError('A file inventory is required.')
    for name, record in files.items():
        _path(name)
        if not isinstance(record, dict):
            raise ValueError('Invalid file inventory record.')
    if 'knownPaths' in value:
        known = value['knownPaths']
        if not isinstance(known, (list, tuple, set, frozenset)) or any(_path(name) != name for name in known):
            raise ValueError('Invalid bounded path inventory.')
        if not set(files).issubset(known):
            raise ValueError('File evidence is outside the bounded inventory.')
    return identity, files


def classify_context(target, inventory, *, original_inventory=None, field_key='field'):
    """Classify a preserved anchor against a verified selected revision.

    Return ``status``, a stable ``reason`` code, a deep copy of ``anchor``,
    canonical ``checkedScope`` and ``evidence``. Only confirmed results have
    ``verified=True``. Invalid, incomplete, foreign or failed-read inventories
    are unavailable, never proof of deletion. Duplicate/conflicting stable
    identities are ambiguous. Optional original-revision SHA256 evidence can
    prove that the containing file changed; it does not prove object changes.
    """
    original = deepcopy(target)
    checked = None
    provenance = None

    def result(status, reason, **evidence):
        if provenance is not None:
            evidence['provenance'] = provenance
        return dict(status=status, reason=reason, anchor=deepcopy(original),
                    checkedScope=deepcopy(checked), verified=status in _CONFIRMED,
                    evidence=evidence)

    try:
        identity = _identity(target)
        path = _path(target.get('file'))
        _name(field_key)
        identifiers = [_name(target[key]) for key in ('uuid', 'objectId') if key in target]
        variant = _name(target['variant'], 100) if 'variant' in target else None
        field = _name(target[field_key], 500) if field_key in target else None
        if 'reference' in target:
            _name(target['reference'], 100)
        context = target.get('context')
        source_hashes = {}
        if context is not None:
            if not isinstance(context, dict) or context.get('type') not in ('bom', 'gerber'):
                raise ValueError('Unsupported context type.')
            if context['type'] == 'gerber':
                path = _path(context.get('file'))
                source_hashes[path] = _digest(context.get('sha256'))
                # Origin PCB UUIDs are not identities of manufacturing objects.
                identifiers, field = [], None
            else:
                identifiers = [_name(context.get('rowId'))]
                field = _name(context['field'], 500) if 'field' in context else None
                sources = context.get('sourceFiles')
                if not isinstance(sources, dict) or not sources:
                    raise ValueError('BOM source provenance is required.')
                source_hashes = {_path(name): _digest(digest) for name, digest in sources.items()}
    except (ValueError, TypeError):
        return result('unavailable', 'invalid-anchor')

    try:
        checked, files = _verified_inventory(inventory)
        provenance = inventory.get('provenance')
    except (ValueError, TypeError):
        return result('unavailable', 'inventory-unavailable')
    if any(identity[key] != checked[key] for key in ('provider', 'host', 'repository')):
        return result('unavailable', 'different-repository')
    if len(set(identifiers)) > 1:
        return result('ambiguous', 'conflicting-object-identities')
    object_id = identifiers[0] if identifiers else None
    if 'knownPaths' in inventory and not {path, *source_hashes}.issubset(inventory['knownPaths']):
        return result('unavailable', 'path-inventory-unavailable')
    record = files.get(path)
    if record is None:
        return result('orphan', 'missing-file', file=path)
    for source in source_hashes:
        if source not in files:
            return result('orphan', 'missing-source-file', file=source)
    if context is not None and context['type'] == 'bom' and record.get('bomComplete') is not True:
        return result('unavailable', 'bom-inventory-unavailable')

    try:
        if object_id is not None:
            if 'objectIds' not in record:
                return result('unavailable', 'object-inventory-unavailable')
            objects = _members(record['objectIds'])
            count = objects.count(object_id)
            if count > 1:
                return result('ambiguous', 'duplicate-object-identity', objectId=object_id)
            if count == 0:
                return result('orphan', 'missing-object', file=path, objectId=object_id)
        elif (context is None and ('reference' in target or field is not None or target.get('kind') == 'bom')):
            return result('unavailable', 'stable-object-identity-required')
        if variant is not None and variant != '*':
            if 'variants' not in inventory and 'variants' not in record:
                return result('unavailable', 'variant-inventory-unavailable')
            variants = _members(inventory['variants'] if 'variants' in inventory else record['variants'])
            if variants.count(variant) > 1:
                return result('ambiguous', 'duplicate-variant', variant=variant)
            if variant not in variants:
                return result('orphan', 'missing-variant', file=path, variant=variant)
        if field is not None:
            fields = record.get('fieldsByObject')
            if not isinstance(fields, dict) or object_id not in fields:
                return result('unavailable', 'field-inventory-unavailable')
            names = _members(fields[object_id], 500)
            if names.count(field) > 1:
                return result('ambiguous', 'duplicate-field', field=field)
            if field not in names:
                return result('orphan', 'missing-field', file=path, objectId=object_id, field=field)
    except (ValueError, TypeError):
        return result('unavailable', 'invalid-identity-inventory')

    changed_sources = []
    for source, expected_hash in source_hashes.items():
        if source not in files:
            return result('orphan', 'missing-source-file', file=source)
        try:
            actual_hash = _digest(files[source].get('sha256'))
        except ValueError:
            return result('unavailable', 'source-digest-unavailable', file=source)
        if actual_hash != expected_hash:
            changed_sources.append(dict(file=source, originalSha256=expected_hash, selectedSha256=actual_hash))
    if changed_sources:
        return result('changed', 'source-content-changed', files=sorted(changed_sources, key=lambda item: item['file']))

    if original_inventory is not None:
        try:
            before_scope, before_files = _verified_inventory(original_inventory)
            before = before_files.get(path, {}).get('sha256')
            after = record.get('sha256')
            if (before_scope == identity and isinstance(before, str) and isinstance(after, str)
                    and _SHA256.fullmatch(before) and _SHA256.fullmatch(after)
                    and before.lower() != after.lower()):
                return result('changed', 'file-content-changed', file=path,
                              originalSha256=before.lower(), selectedSha256=after.lower())
        except (ValueError, TypeError):
            # Failure to obtain the old file does not negate current existence.
            pass
    if identity['ref'] == checked['ref']:
        return result('current', 'identity-present', file=path)
    return result('older-revision', 'identity-present-at-other-revision', file=path)


def propose_status_event(classification, comment_id, *, previous_event_id=None):
    """Return deterministic append-only event data, or None without proof.

    The caller must freshly revalidate evidence and obtain any required user
    approval before publishing. Reuse ``eventId`` to detect an already-published
    event; supply the latest authoritative ``previous_event_id`` to distinguish
    a repeated transition after recovery from a duplicate observation. Without
    that predecessor this is a state key, not an ordered transition identity.
    Provider-side atomicity and comment ownership are not decided here.
    No timestamps, local paths, credentials or inventory error text are included.
    """
    if (not isinstance(classification, dict) or classification.get('verified') is not True
            or classification.get('status') not in _CONFIRMED):
        return None
    _name(comment_id, 200)
    payload = dict(schemaVersion=1, type='review-context-status', commentId=comment_id,
                   status=classification['status'], reason=classification['reason'],
                   anchor=deepcopy(classification['anchor']),
                   checkedScope=deepcopy(classification['checkedScope']),
                   evidence=deepcopy(classification['evidence']))
    if previous_event_id is not None:
        payload['previousEventId'] = _digest(previous_event_id)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return dict(payload, eventId=hashlib.sha256(encoded.encode('utf-8')).hexdigest())
