"""Data-only BOM/Gerber context linked to the unchanged online v1 anchor."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import math
from pathlib import PurePosixPath
import re

CONTEXT_MARKER = re.compile(r'<!-- wayricad-context:v1 ([A-Za-z0-9_-]{1,32000}) -->')
STATUS_MARKER = re.compile(r'<!-- wayricad-status:v1 ([A-Za-z0-9_-]{1,60000}) -->')
GERBER_SUFFIXES = {'.gbr', '.ger', '.gerber', '.gtl', '.gbl', '.gts', '.gbs', '.gto', '.gbo', '.gtp', '.gbp', '.gm1', '.gko', '.drl'}


def visible_body(body):
    from .model import MARKER
    return STATUS_MARKER.sub('', CONTEXT_MARKER.sub('', MARKER.sub('', body))).strip()


def relative_path(value):
    if (not isinstance(value, str) or not value or len(value) > 500 or value.startswith('/')
            or '\\' in value or ':' in value or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('Context paths must stay inside the project.')
    return value


def _text(value, label, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid context ' + label)
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Context needs an exact saved-file SHA-256.')
    return value


def validate_context(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid review context.')
    kind = value.get('type')
    if kind == 'bom':
        if set(value) - {'type', 'rowId', 'field', 'sourceFiles'}:
            raise ValueError('Unsupported BOM context fields.')
        result = dict(type=kind, rowId=_text(value.get('rowId'), 'BOM row ID'))
        if 'field' in value:
            result['field'] = _text(value['field'], 'BOM field', 500)
        sources = value.get('sourceFiles')
        if not isinstance(sources, dict) or not 1 <= len(sources) <= 64:
            raise ValueError('BOM context needs 1–64 saved sources.')
        result['sourceFiles'] = {relative_path(k): _sha(v) for k, v in sorted(sources.items())}
        if any(PurePosixPath(k).suffix.lower() not in ('.kicad_sch', '.kicad_pcb', '.kicad_pro') for k in sources):
            raise ValueError('Unsupported BOM source type.')
        return result
    if kind != 'gerber' or set(value) - {'type', 'file', 'sha256', 'position', 'area'}:
        raise ValueError('Unsupported review context type or fields.')
    result = dict(type=kind, file=relative_path(value.get('file')), sha256=_sha(value.get('sha256')))
    if PurePosixPath(result['file']).suffix.lower() not in GERBER_SUFFIXES:
        raise ValueError('Choose a supported local Gerber or drill file.')
    if 'position' in value and 'area' in value:
        raise ValueError('Choose a point or region, not both.')
    for key, fields in (('position', ('x', 'y')), ('area', ('x', 'y', 'width', 'height'))):
        if key in value:
            box = value[key]
            if (not isinstance(box, dict) or set(box) != set(fields) or
                any(isinstance(box.get(f), bool) or not isinstance(box.get(f), (int, float)) or
                    not math.isfinite(box[f]) or abs(box[f]) > 1e6 for f in fields)):
                raise ValueError('Invalid manufacturing coordinates.')
            if key == 'area' and (box['width'] <= 0 or box['height'] <= 0):
                raise ValueError('A region needs positive dimensions.')
            result[key] = dict(box)
    return result


def anchor_hash(target):
    legacy = {k: v for k, v in target.items() if k != 'context'}
    return hashlib.sha256(json.dumps(legacy, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def context_markdown(identifier, target):
    context = validate_context(target['context'])
    payload = dict(id=_text(identifier, 'annotation ID', 100), anchorHash=anchor_hash(target), context=context)
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()).decode().rstrip('=')
    if len(encoded) > 32000:
        raise ValueError('Review context exceeds the wire-format limit.')
    return '<!-- wayricad-context:v1 ' + encoded + ' -->'


def attach_contexts(body, annotations):
    """Malformed, duplicate or mismatched extensions never authorize a context."""
    extensions = {}
    for match in list(CONTEXT_MARKER.finditer(body))[:100]:
        try:
            value = json.loads(base64.b64decode(match[1] + '=' * (-len(match[1]) % 4), altchars=b'-_', validate=True))
            if not isinstance(value, dict) or set(value) != {'id', 'anchorHash', 'context'}:
                continue
            key = (_text(value['id'], 'annotation ID', 100), _sha(value['anchorHash']))
            extensions.setdefault(key, []).append(validate_context(value['context']))
        except (ValueError, KeyError, TypeError, RecursionError):
            continue
    result = deepcopy(annotations)
    for annotation in result:
        candidates = extensions.get((annotation.get('id'), anchor_hash(annotation['anchor'])), [])
        if len(candidates) == 1:
            annotation['anchor']['context'] = candidates[0]
    return result


def verify_target(target, root):
    """Verify every saved context source immediately before explicit publication."""
    from pathlib import Path
    from .model import unchanged
    from .project_artifacts import local_file
    context = target.get('context')
    variant = target.get('variant', '*')
    if not context and variant == '*':
        return
    root = Path(root).resolve(strict=True)
    if context and context['type'] == 'gerber':
        project = local_file(root, root / target['file']).parent
        path = local_file(project, root / context['file'])
        unchanged(path, context['sha256'])
    if context and context['type'] == 'bom' or variant != '*':
        from .bom_review import load_bom
        snapshot = load_bom(local_file(root, root / target['file']), root=root)
        if variant != '*' and variant not in snapshot['variants']:
            raise ValueError('The selected variant no longer exists in the saved design.')
        if context and context['type'] == 'bom':
            if snapshot['source_hashes'] != context['sourceFiles']:
                raise ValueError('BOM sources changed. Reload the field table and attach the cell again.')
            row = next((r for r in snapshot['rows'] if r['id'] == context['rowId']), None)
            if row is None or context.get('field') and context['field'] not in row['fields']:
                raise ValueError('The BOM row or field no longer exists.')
