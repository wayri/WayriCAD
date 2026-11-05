"""Fresh-read diagnostics and conservative append-only context status updates.

Caller-supplied rows must be a complete, authorized provider snapshot. The
provider must retain its own authorization checks on every read and write.
This module never edits/deletes author comments, navigates, or writes designs.
Cross-client deduplication is best effort: provider APIs do not offer an atomic
compare-and-append operation. An uncertain write halts this tracker instance.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import re

from .context_status import _identity, classify_context, propose_status_event
from .model import anchor, project_markers
from .project_context import MAX_ANNOTATIONS, build_inventory


MAX_ROWS = 5001
STATUS_MARKER = re.compile(r'<!-- wayricad-status:v1 ([A-Za-z0-9_-]{1,60000}) -->')
_STATES = {'current', 'older-revision', 'changed', 'orphan'}
_KEYS = {'schemaVersion', 'type', 'commentId', 'annotationId', 'status', 'reason',
         'anchor', 'checkedScope', 'evidence', 'eventId', 'previousEventId'}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _identifier(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 200 or
            value != value.strip() or any(ord(char) < 32 for char in value)):
        raise ValueError('Invalid context status identity.')
    return value


def _event_id(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid context status event ID.')
    return value


def make_status_event(classification, comment_id, annotation_id, previous_event_id=None):
    event = propose_status_event(classification, _identifier(comment_id), previous_event_id=previous_event_id)
    if event is None:
        return None
    event.pop('eventId')
    event['annotationId'] = _identifier(annotation_id)
    event['eventId'] = _hash(event)
    return event


def _original_comment(event, provider):
    identifier = event['commentId']
    label = 'comment ' + identifier if re.fullmatch('[A-Za-z0-9_=:-]{1,200}', identifier) else 'the original comment'
    if not identifier.isascii() or not identifier.isdecimal() or provider is None:
        return label
    identity = _identity(event['anchor'])
    kind, number = getattr(provider, 'kind', None), getattr(provider, 'number', None)
    if (type(number) is not int or number < 1 or kind not in ('issue', 'pull', 'merge_request') or
            getattr(provider, 'provider', None) != identity['provider'] or
            getattr(provider, 'repository', None) != identity['repository'] or
            getattr(provider, 'origin', None) != identity['host']):
        return label
    if identity['provider'] == 'github':
        if kind == 'merge_request':
            return label
        url = identity['host'] + '/' + identity['repository'] + ('/pull/' if kind == 'pull' else '/issues/') + str(number)
        url += '#issuecomment-' + identifier
    else:
        if kind == 'pull':
            return label
        url = identity['host'] + '/' + identity['repository'] + '/-/' + ('merge_requests/' if kind == 'merge_request' else 'issues/') + str(number)
        url += '#note_' + identifier
    return '[' + label + '](' + url + ')'


def status_markdown(event, provider=None):
    encoded = base64.urlsafe_b64encode(_json(event).encode()).decode().rstrip('=')
    if len(encoded) > 60000:
        raise ValueError('Context status event exceeds its publication bound.')
    descriptions = {'current': 'The original context is available again.',
                    'older-revision': 'The original context exists at another saved revision.',
                    'changed': 'The saved context has changed since this annotation.',
                    'orphan': 'The original context is missing from the observed saved files.'}
    reason = event['reason'].replace('-', ' ') if re.fullmatch('[a-z-]{1,100}', event['reason']) else 'context evidence changed'
    revision = _identity(event['checkedScope'])['ref']
    provenance = event['evidence'].get('provenance')
    if provenance == 'working-tree':
        observation = ('Local saved working-tree observation; HEAD baseline: ' + revision +
                       '. Saved files may include uncommitted changes.')
        if event['status'] == 'older-revision':
            descriptions['older-revision'] = 'The original context is available against a different HEAD baseline.'
    elif provenance == 'git-commit':
        observation = 'Checked saved files at revision ' + revision + '.'
    else:
        observation = 'Observed saved context; comparison revision: ' + revision + '. Inventory provenance was not supplied.'
    return ('Review context update for ' + _original_comment(event, provider) + ': ' + descriptions[event['status']] +
            '\n\nReason: ' + reason + '. ' + observation + '\n\n'
            '<!-- wayricad-status:v1 ' + encoded + ' -->')


def parse_status_events(rows, current_scope):
    """Parse bounded, self-consistent events belonging to this exact project.

    Hashes detect inconsistent payloads; they are not signatures or proof of a
    comment author's identity. Events only deduplicate status publication.
    """
    expected = _identity(current_scope)
    result, inspected = [], 0
    for row in rows:
        for match in STATUS_MARKER.finditer(row['body']):
            inspected += 1
            if inspected > MAX_ANNOTATIONS:
                raise ValueError('Too many context status events.')
            try:
                event = json.loads(base64.b64decode(match[1] + '=' * (-len(match[1]) % 4), altchars=b'-_', validate=True))
                if (not isinstance(event, dict) or set(event) - _KEYS or
                        _KEYS - {'previousEventId'} - set(event) or
                        type(event['schemaVersion']) is not int or event['schemaVersion'] != 1 or
                        event['type'] != 'review-context-status' or event['status'] not in _STATES or
                        not isinstance(event['reason'], str) or not re.fullmatch('[a-z-]{1,100}', event['reason']) or
                        not isinstance(event['evidence'], dict)):
                    continue
                if ('provenance' in event['evidence'] and
                        event['evidence']['provenance'] not in ('working-tree', 'git-commit')):
                    continue
                _identifier(event['commentId'])
                _identifier(event['annotationId'])
                identifier = _event_id(event['eventId'])
                if 'previousEventId' in event:
                    _event_id(event['previousEventId'])
                if identifier != _hash({key: value for key, value in event.items() if key != 'eventId'}):
                    continue
                if anchor(event['anchor']) != event['anchor']:
                    continue
                for candidate in (event['anchor'], event['checkedScope']):
                    identity = _identity(candidate)
                    if any(identity[key] != expected[key] for key in ('provider', 'host', 'repository')):
                        raise ValueError('Foreign context event.')
                result.append(event)
            except (ValueError, TypeError, KeyError, RecursionError):
                continue
    return result


def _latest(events, key, target):
    related = {item['eventId']: item for item in events
               if (item['commentId'], item['annotationId']) == key and item['anchor'] == target}
    if not related:
        return None, False
    children, roots = {}, []
    for identifier, item in related.items():
        previous = item.get('previousEventId')
        if previous is None:
            roots.append(identifier)
        elif previous not in related:
            return None, True
        else:
            children.setdefault(previous, []).append(identifier)
    if len(roots) != 1 or any(len(values) != 1 for values in children.values()):
        return None, True
    seen, identifier = set(), roots[0]
    while identifier not in seen:
        seen.add(identifier)
        if identifier not in children:
            return (related[identifier], False) if len(seen) == len(related) else (None, True)
        identifier = children[identifier][0]
    return None, True


def _state(value):
    # A new HEAD alone is not another status transition when context evidence is
    # unchanged. The emitted event still records the exact observed revision.
    return _hash({key: value[key] for key in ('status', 'reason', 'anchor', 'evidence')})


def _candidate(classification, events, key):
    if classification.get('verified') is not True:
        return None, False
    previous, ambiguous = _latest(events, key, classification['anchor'])
    if ambiguous:
        return None, True
    if previous and _state(previous) == _state(classification):
        return None, False
    status = classification['status']
    if status not in ('orphan', 'changed') and not (
            status in ('current', 'older-revision') and previous and previous['status'] in ('orphan', 'changed')):
        return None, False
    return make_status_event(classification, *key,
                             previous_event_id=previous['eventId'] if previous else None), False


def _collect(rows, current_scope):
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError('Context refresh requires at most 5001 complete provider rows.')
    entries, copies, identifiers, note_ids = [], [], set(), {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('body'), str) or len(row['body'].encode()) > 1024 * 1024:
            raise ValueError('Invalid provider context row.')
        identifier = _identifier(row.get('id'))
        if identifier in identifiers:
            raise ValueError('Duplicate provider context row identity.')
        identifiers.add(identifier)
        copies.append(dict(row, contextStatus=[], annotations=list(row.get('annotations', [])),
                           anchors=list(row.get('anchors', []))))
        for annotation in project_markers(row['body'], current_scope):
            try:
                note_id = _identifier(annotation['id'])
            except ValueError:
                continue
            if len(entries) >= MAX_ANNOTATIONS:
                raise ValueError('Context annotation limit exceeded.')
            entry = dict(index=index, key=(identifier, note_id), annotation=annotation)
            entries.append(entry)
            note_ids.setdefault(note_id, []).append(entry)
    for entry in entries:
        target = entry['annotation']['anchor']
        if len(note_ids[entry['key'][1]]) != 1:
            entry['blocked'] = 'duplicate-annotation-identity'
        elif (target.get('kind') in ('bom', 'bom-field', 'gerber') or
              str(target.get('objectId', '')).startswith(('bom:', 'gerber:'))) and 'context' not in target:
            entry['blocked'] = 'context-extension-unavailable'
    return copies, entries


class ContextTracker:
    def __init__(self, *, inventory_builder=build_inventory):
        self.inventory_builder = inventory_builder
        self.warning = None
        self.halted = False
        self._observations = {}
        self._pending = None

    def _assess(self, rows, root, current_scope):
        copies, entries = _collect(rows, current_scope)
        annotations = [entry['annotation'] for entry in entries if 'blocked' not in entry]
        inventory = self.inventory_builder(root, current_scope, annotations) if annotations else {}
        assessed = {}
        for entry in entries:
            target, key = entry['annotation']['anchor'], entry['key']
            if 'blocked' in entry:
                classification = dict(status='ambiguous' if entry['blocked'].startswith('duplicate') else 'unavailable',
                                      reason=entry['blocked'], anchor=deepcopy(target), checkedScope=None,
                                      verified=False, evidence={})
            else:
                baseline = inventory.get('originalInventories', {}).get(target['ref'])
                classification = classify_context(target, inventory, original_inventory=baseline)
            copies[entry['index']]['contextStatus'].append(dict(classification, annotationId=key[1]))
            if 'blocked' not in entry:
                assessed[key] = classification
        fingerprint = _hash(inventory)
        return copies, assessed, fingerprint, parse_status_events(copies, current_scope)

    def update(self, rows, provider, root, current_scope, auto_publish=True, *, prepublish=None):
        """Classify a fresh snapshot; at most one stable status update is posted.

        Two consecutive identical verified observations are required. A fresh
        provider snapshot and identical local inventory are checked immediately
        before the one-shot append. A timeout/uncertain receipt is never retried
        by this instance, even if subsequent snapshots omit the possible write.
        Optional ``prepublish()`` runs after all preflight reads, immediately
        before publication. It should assert caller authorization/source guards;
        a raised exception establishes no-send and does not halt as uncertain.
        """
        if not self.halted:
            self.warning = None
        try:
            result, assessed, fingerprint, events = self._assess(rows, root, current_scope)
        except (ValueError, TypeError, KeyError, OSError):
            self._observations = {}
            if not self.halted:
                self.warning = 'Context diagnostics require a complete, unambiguous provider and saved-project snapshot.'
            return rows
        observed = {}
        for key, classification in assessed.items():
            if classification.get('verified') is not True:
                continue
            stamp = _hash([classification, fingerprint])
            old_stamp, count = self._observations.get(key, (None, 0))
            observed[key] = stamp, count + 1 if stamp == old_stamp else 1
        self._observations = observed
        if self._pending is not None:
            if any(event['eventId'] == self._pending for event in events):
                self._pending = None
            else:
                if not self.halted:
                    self.warning = 'The last context update awaits provider readback; no additional automatic update was sent.'
                return result
        if self.halted or auto_publish is not True:
            return result
        for key, classification in assessed.items():
            if observed.get(key, ('', 0))[1] < 2:
                continue
            event, ambiguous = _candidate(classification, events, key)
            if ambiguous:
                self.warning = 'Context status history is ambiguous; automatic updates for that annotation are paused.'
                continue
            if event is None:
                continue
            try:
                provider_scope = _identity(provider.scope)
                expected_scope = _identity(current_scope)
                if any(provider_scope[name] != expected_scope[name] for name in ('provider', 'host', 'repository')):
                    raise ValueError('Provider context belongs to another project.')
            except (AttributeError, ValueError, TypeError):
                self.warning = 'The provider destination does not match this context project; no automatic update was sent.'
                return result
            try:
                latest_rows = provider.snapshot()
                if not isinstance(latest_rows, list) or len(latest_rows) > MAX_ROWS:
                    raise ValueError('Invalid preflight provider snapshot.')
                # Preserve caller-derived authority only for unchanged provider
                # bodies. New/edited rows wait for the session's own checks.
                previous_rows = {row['id']: row for row in rows}
                for latest_row in latest_rows:
                    previous_row = previous_rows.get(latest_row.get('id'))
                    if previous_row and previous_row.get('body') == latest_row.get('body'):
                        for name in ('annotations', 'anchors'):
                            if name in previous_row:
                                latest_row[name] = deepcopy(previous_row[name])
                latest, latest_assessed, latest_fingerprint, latest_events = self._assess(latest_rows, root, current_scope)
            except Exception:
                self._observations.pop(key, None)
                self.warning = 'Context update preflight could not be verified; no status update was sent.'
                return result
            result = latest
            fresh = latest_assessed.get(key)
            if fresh != classification or latest_fingerprint != fingerprint:
                self._observations.pop(key, None)
                self.warning = 'Context or provider annotation changed during preflight; no status update was sent.'
                return result
            event, ambiguous = _candidate(fresh, latest_events, key)
            if event is None or ambiguous:
                if ambiguous:
                    self.warning = 'Context status history is ambiguous; no automatic update was sent.'
                return result
            try:
                body = status_markdown(event, provider)
            except ValueError:
                self.warning = 'Context status metadata exceeds its publication bound; no automatic update was sent.'
                return result
            try:
                if prepublish is not None:
                    prepublish()
            except Exception:
                self._observations.pop(key, None)
                self.warning = 'Context publication guard failed; recheck authorization and the selected saved source. No status update was sent.'
                return result
            try:
                receipt = provider.publish(body)
                if not isinstance(receipt, str) or not receipt.strip():
                    raise ValueError('Missing publication receipt.')
            except Exception:
                self.halted = True
                self.warning = 'Context status publication is uncertain. Automatic updates are halted; inspect the provider before an explicit restart.'
                return result
            self._pending = event['eventId']
            return result
        return result
