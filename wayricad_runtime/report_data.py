"""Lossless, offline storage for large interactive report payloads."""
from __future__ import annotations

import base64
import gzip
import json

THRESHOLD = 128 * 1024


def script_json(value):
    """Return a safe JS expression and whether its caller must be async.

    Small plots retain their synchronous JSON form. Large payloads use standard
    gzip with no decimal rounding, sample removal or external network request.
    Static report figures and exact sidecars remain available in older browsers.
    """
    raw = json.dumps(value, allow_nan=False).replace('<', '\\u003c')
    if len(raw.encode('utf-8')) < THRESHOLD:
        return raw, False
    compact = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    encoded = base64.b64encode(gzip.compress(compact, compresslevel=9, mtime=0)).decode('ascii')
    expression = ('await (async()=>{if(typeof DecompressionStream!=="function")'
        '{throw new Error("this browser cannot decompress saved plots");}'
        'const bytes=Uint8Array.from(atob("'+encoded+'"),c=>c.charCodeAt(0));'
        'const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));'
        'return JSON.parse(await new Response(stream).text());})()')
    return expression, True
