"""Small lossless-at-the-atom-level KiCad s-expression reader/writer.

Unknown lists are retained. Transformations must be structural, never regex edits
on entire KiCad files. Comments/whitespace are not retained; numeric lexemes are.
"""
from __future__ import annotations
from pathlib import Path
import re
import hashlib

class FormatError(ValueError):
    pass

class Quoted(str):
    """A quoted string, distinguished from a KiCad bare token."""


def q(value):
    return Quoted(str(value))


def tag(node):
    return str(node[0]) if isinstance(node, list) and node and isinstance(node[0], str) else ""


def children(node, name=None):
    return [v for v in node[1:] if isinstance(v, list) and (name is None or tag(v) == name)]


def child(node, name, default=None):
    return next((v for v in node[1:] if isinstance(v, list) and tag(v) == name), default)


def value(node, name, default=""):
    n = child(node, name)
    return str(n[1]) if n is not None and len(n) > 1 else default


def prop(node, name):
    for p in children(node, 'property'):
        index = 2 if len(p)>1 and p[1]=='private' and not isinstance(p[1],Quoted) else 1
        if len(p)>index+1 and str(p[index]).casefold()==name.casefold():
            return p
    return None


def propval(node, name, default=""):
    p=prop(node,name)
    if p is None:
        return default
    index=3 if len(p)>1 and p[1]=='private' and not isinstance(p[1],Quoted) else 2
    return str(p[index])


def put(node, name, *args):
    # Preserve header/token order: KiCad needs the file version before any
    # version-dependent syntax (notably layer and net declarations).
    positions = [i for i, old in enumerate(node) if isinstance(old, list) and tag(old) == name]
    n = [name, *args]
    if positions:
        node[positions[0]] = n
        for i in reversed(positions[1:]):
            del node[i]
    else:
        node.append(n)
    return n


def remove(node, name):
    node[:] = [n for n in node if not (isinstance(n, list) and tag(n) == name)]


def walk(node):
    if isinstance(node, list):
        yield node
        for n in node:
            if isinstance(n, list):
                yield from walk(n)


def loads(text: str):
    stack, roots = [], []
    i, size = 0, len(text)
    while i < size:
        c = text[i]
        if c.isspace() or c == '\ufeff':
            i += 1
            continue
        if c == ';':
            end = text.find('\n', i)
            i = size if end < 0 else end + 1
            continue
        if c == '(':
            n = []
            (stack[-1] if stack else roots).append(n)
            stack.append(n)
            if len(stack) > 180:
                raise FormatError("S-expression nesting exceeds 180 levels")
            i += 1
        elif c == ')':
            if not stack:
                raise FormatError(f"Unmatched ')' at character {i}")
            stack.pop()
            i += 1
        elif c == '"':
            i += 1
            out = []
            while i < size and text[i] != '"':
                if text[i] == '\\':
                    i += 1
                    if i >= size:
                        raise FormatError("Unterminated string escape")
                    e = text[i]
                    out.append({'n':'\n', 'r':'\r', 't':'\t', '"':'"', '\\':'\\'}.get(e, '\\' + e))
                else:
                    out.append(text[i])
                i += 1
            if i >= size:
                raise FormatError("Unterminated quoted string")
            i += 1
            if not stack:
                raise FormatError("String outside root expression")
            stack[-1].append(q(''.join(out)))
        else:
            j = i
            while i < size and not text[i].isspace() and text[i] not in '();':
                i += 1
            if not stack:
                raise FormatError("Token outside root expression")
            stack[-1].append(text[j:i])
    if stack or len(roots) != 1 or not roots[0]:
        raise FormatError("Expected one balanced, non-empty root expression")
    return roots[0]


def atom(v):
    if isinstance(v, Quoted):
        return '"' + str(v).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\r','\\r').replace('\t','\\t') + '"'
    if not isinstance(v, str):
        raise TypeError(f"S-expression atom must be str, not {type(v).__name__}")
    return v


def dumps(node, depth=0):
    if not isinstance(node, list):
        return atom(node)
    if not any(isinstance(n, list) for n in node):
        return '(' + ' '.join(atom(n) for n in node) + ')'
    chunks = []
    for n in node:
        if isinstance(n, list):
            chunks.append('\n' + '  '*(depth+1) + dumps(n, depth+1))
        else:
            chunks.append((' ' if chunks else '') + atom(n))
    return '(' + ''.join(chunks) + '\n' + '  '*depth + ')'


def load(path, hashes=None):
    path = Path(path)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise FormatError(f"File exceeds 512 MiB safety limit: {path}")
    data = path.read_bytes()
    if len(data) > 512 * 1024 * 1024:
        raise FormatError(f"File exceeds 512 MiB safety limit: {path}")
    if hashes is not None:
        key = str(path.resolve())
        digest = hashlib.sha256(data).hexdigest()
        if key in hashes and hashes[key] != digest:
            raise FormatError(f"Source changed during preflight: {path}")
        hashes[key] = digest
    return loads(data.decode('utf-8-sig'))


def save(path, node):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dumps(node) + '\n', encoding='utf-8', newline='\n')


UUID_RE = re.compile(r'^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$')


def declared_uuids(node):
    """Object identities, excluding KiCad's dimension-label identity alias.

    A dimension's nested gr_text repeats its owner's UUID in native KiCad 10
    saves. It is not a second independently identified board object. Keep all
    other duplicates visible so callers can reject malformed input.
    """
    result = []

    def visit(current, dimension_label_id=None):
        for item in current:
            if not isinstance(item, list):
                continue
            if tag(item) in {'uuid', 'tstamp', 'id'} and len(item) == 2:
                ident = str(item[1])
                if UUID_RE.fullmatch(ident) and not (
                        tag(item) == 'uuid' and ident == dimension_label_id):
                    result.append(ident)
            else:
                alias = value(current, 'uuid') if (
                    tag(current) == 'dimension' and tag(item) == 'gr_text') else None
                visit(item, alias)

    visit(node)
    return result


def remap_identifiers(node, mapping):
    """Only identifiers and structured text-variable targets; not arbitrary prose."""
    for n in walk(node):
        if tag(n) in {'uuid','tstamp','id'} and len(n)==2 and str(n[1]) in mapping:
            n[1] = q(mapping[str(n[1])])
        elif tag(n) == 'members':
            for i in range(1,len(n)):
                if isinstance(n[i], str) and str(n[i]) in mapping:
                    n[i] = q(mapping[str(n[i])])
        for i, v in enumerate(n):
            if isinstance(v, Quoted) and '${' in v:
                n[i] = q(re.sub(r'\$\{([^}:]+):', lambda m: '${'+mapping.get(m[1],m[1])+':', str(v)))
