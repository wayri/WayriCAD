"""Span-preserving reader. Never serializes unrelated KiCad syntax.

This deliberately is not a complete KiCad interpreter. Unknown nodes remain in the
original document; higher layers reject writes when their meaning is not known.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json

@dataclass
class Atom:
    value: str
    start: int
    end: int
    quoted: bool = False

@dataclass
class Node:
    start: int
    end: int = 0
    atoms: list[Atom] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)

    @property
    def tag(self) -> str:
        return self.atoms[0].value if self.atoms else ""

    def nodes(self, tag: str) -> list[Node]:
        return [n for n in self.children if n.tag == tag]

    def one(self, tag: str) -> Node | None:
        return next((n for n in self.children if n.tag == tag), None)

    def val(self, index: int = 1, default: str = "") -> str:
        return self.atoms[index].value if len(self.atoms) > index else default

    def get(self, tag: str, default: str = "") -> str:
        n = self.one(tag)
        return n.val(default=default) if n else default


def parse(text: str) -> Node:
    stack: list[Node] = []
    roots: list[Node] = []
    i, length, count = 0, len(text), 0
    while i < length:
        c = text[i]
        if c.isspace() or c == '\ufeff':
            i += 1
            continue
        if c in '#;':
            j = text.find('\n', i)
            i = length if j < 0 else j + 1
            continue
        if c == '(':
            n = Node(i)
            (stack[-1].children if stack else roots).append(n)
            stack.append(n)
            count += 1
            if len(stack) > 512 or count > 2_000_000:
                raise ValueError('S-expression exceeds safety limits.')
            i += 1
            continue
        if c == ')':
            if not stack:
                raise ValueError(f'Unexpected closing parenthesis at {i}.')
            stack.pop().end = i + 1
            i += 1
            continue
        if not stack:
            raise ValueError(f'Unexpected text outside root at {i}.')
        start = i
        if c == '"':
            i += 1
            value: list[str] = []
            while i < length and text[i] != '"':
                if text[i] == '\\':
                    i += 1
                    if i >= length:
                        raise ValueError('Unterminated string escape.')
                    esc = text[i]
                    value.append({'n':'\n','r':'\r','t':'\t','"':'"','\\':'\\'}.get(esc, '\\' + esc))
                else:
                    value.append(text[i])
                i += 1
            if i >= length:
                raise ValueError('Unterminated string.')
            i += 1
            stack[-1].atoms.append(Atom(''.join(value), start, i, True))
        else:
            while i < length and not text[i].isspace() and text[i] not in '()':
                i += 1
            stack[-1].atoms.append(Atom(text[start:i], start, i))
    if stack or len(roots) != 1:
        raise ValueError('Expected one complete S-expression root.')
    return roots[0]


def quote(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def properties(node: Node) -> dict[str, tuple[str, Node, Atom]]:
    result = {}
    for p in node.nodes('property'):
        idx = 2 if len(p.atoms) > 1 and p.atoms[1].value == 'private' and not p.atoms[1].quoted else 1
        if len(p.atoms) <= idx + 1:
            raise ValueError('Malformed property.')
        name, value = p.atoms[idx].value, p.atoms[idx + 1]
        if name in result:
            raise ValueError(f'Duplicate property: {name}. Resolve it in KiCad first.')
        result[name] = (value.value, p, value)
    return result


def apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    # Coalesce insertions at the same offset and reject ambiguous overlapping edits.
    unique: dict[tuple[int, int], str] = {}
    for start, end, value in edits:
        if not 0 <= start <= end <= len(text):
            raise ValueError('Patch is outside the document.')
        key = (start, end)
        if key in unique:
            if start == end:
                unique[key] += value
            elif unique[key] != value:
                raise ValueError('Conflicting edits to a shared symbol. Use a named variant.')
        else:
            unique[key] = value
    ordered = sorted((a, b, v) for (a, b), v in unique.items())
    last = 0
    chunks: list[str] = []
    for start, end, value in ordered:
        if start < last:
            raise ValueError('Overlapping native edits were blocked.')
        chunks.extend((text[last:start], value))
        last = end
    chunks.append(text[last:])
    return ''.join(chunks)
