"""Span-preserving KiCad S-expression reader. No whole-file reserialization."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator, Union

class FormatError(ValueError):
    pass

@dataclass(frozen=True)
class Atom:
    start: int
    end: int
    kind: str = 'atom'

    def value(self, text: str) -> str:
        raw = text[self.start:self.end]
        if self.kind != 'string':
            return raw
        out, i = [], 1
        while i < len(raw)-1:
            if raw[i] == '\\' and i+1 < len(raw)-1:
                i += 1
                out.append({'n': '\n', 'r': '\r', 't': '\t'}.get(raw[i], raw[i]))
            else:
                out.append(raw[i])
            i += 1
        return ''.join(out)

@dataclass
class Node:
    start: int
    end: int = 0
    children: list[Union['Node', Atom]] = field(default_factory=list)

    def head(self, text: str) -> str:
        return self.children[0].value(text) if self.children and isinstance(self.children[0], Atom) else ''

    def nodes(self, text: str, name: str) -> list['Node']:
        return [c for c in self.children if isinstance(c, Node) and c.head(text) == name]

    def one(self, text: str, name: str) -> 'Node | None':
        found = self.nodes(text, name)
        if len(found) > 1:
            raise FormatError('Duplicate (%s ...) block' % name)
        return found[0] if found else None

    def arg(self, index: int = 1) -> Atom:
        if index >= len(self.children) or not isinstance(self.children[index], Atom):
            raise FormatError('Expected atom at offset %d' % self.start)
        return self.children[index]

    def raw(self, text: str) -> str:
        return text[self.start:self.end]


def tokens(text: str) -> Iterator[Atom]:
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch == '\ufeff':
            i += 1
            continue
        if ch in '#;':
            j = text.find('\n', i)
            i = n if j < 0 else j+1
            continue
        start = i
        if ch in '()':
            i += 1
            yield Atom(start, i, ch)
        elif ch == '"':
            i += 1
            while i < n:
                if text[i] == '\\':
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise FormatError('Unterminated quoted string at %d' % start)
            if i > n:
                raise FormatError('Truncated escape at %d' % start)
            yield Atom(start, i, 'string')
        elif ch == '|':
            i = text.find('|', i+1)
            if i < 0:
                raise FormatError('Unterminated embedded data at %d' % start)
            i += 1
            yield Atom(start, i, 'blob')
        else:
            while i < n and not text[i].isspace() and text[i] not in '()':
                i += 1
            yield Atom(start, i)


def parse(text: str) -> Node:
    roots, stack = [], []
    for t in tokens(text):
        if t.kind == '(':
            node = Node(t.start)
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
            if len(stack) > 256:
                raise FormatError('Excessive nesting')
        elif t.kind == ')':
            if not stack:
                raise FormatError('Unmatched close parenthesis at %d' % t.start)
            stack.pop().end = t.end
        else:
            if not stack:
                raise FormatError('Unexpected data outside the root expression')
            stack[-1].children.append(t)
    if stack or len(roots) != 1:
        raise FormatError('Expected one balanced root expression')
    return roots[0]


def quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'


def patch(text: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply disjoint edits, preserving every other character, including CRLF."""
    cursor, out = 0, []
    for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1])):
        if start < cursor or start > end or end > len(text):
            raise FormatError('Overlapping or invalid edits')
        out.extend((text[cursor:start], replacement))
        cursor = end
    out.append(text[cursor:])
    return ''.join(out)


def semantic(text: str, ignore_embedding: bool = False):
    """Canonical, whitespace-independent structure used by native preflight."""
    root = parse(text)
    def walk(n):
        if isinstance(n, Atom):
            return n.value(text)
        head = n.head(text)
        children = n.children
        if ignore_embedding and head == 'embedded_files':
            return None
        result = []
        for i, c in enumerate(children):
            if ignore_embedding and head == 'model' and i == 1:
                result.append('<MODEL-REFERENCE>')
            else:
                value = walk(c)
                if value is not None:
                    result.append(value)
        return tuple(result)
    return walk(root)
