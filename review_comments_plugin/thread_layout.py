"""Deterministic one-level visual threading for provider conversation rows."""
from __future__ import annotations

from collections import defaultdict


MAX_ROWS = 5001


def flat_threads(rows: list[dict]) -> list[dict]:
    """Place each root before its replies, preserving provider order among peers.

    Input order is the chronology supplied by the provider. Edited timestamps
    are deliberately ignored. Every output is a shallow copy with replyDepth
    0 or 1; malformed relationships are surfaced in replyIssue instead of
    silently attaching them to an arbitrary conversation.
    """
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Review thread snapshot exceeds its supported row limit or contains invalid rows.')
    copies = [dict(row) for row in rows]
    ids = defaultdict(list)
    for index, row in enumerate(copies):
        identifier = row.get('id')
        if isinstance(identifier, str) and identifier:
            ids[identifier].append(index)
    parents: list[int | None] = [None] * len(rows)
    issues: list[str | None] = [None] * len(rows)
    for index, row in enumerate(copies):
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier:
            issues[index] = 'missing-id'
            continue
        if len(ids[identifier]) > 1:
            issues[index] = 'duplicate-id'
            continue
        parent = row.get('parentId')
        if parent is None or parent == '':
            continue
        if not isinstance(parent, str) or not parent:
            issues[index] = 'invalid-parent'
        elif parent not in ids:
            issues[index] = 'missing-parent'
        elif len(ids[parent]) != 1:
            issues[index] = 'ambiguous-parent'
        else:
            parents[index] = ids[parent][0]

    # Each row has at most one parent. Break each cycle at its earliest provider
    # row, keeping every row visible and making its diagnostic deterministic.
    visited = set()
    for start in range(len(rows)):
        if start in visited:
            continue
        chain, positions = [], {}
        current = start
        while current is not None and current not in visited and current not in positions:
            positions[current] = len(chain)
            chain.append(current)
            current = parents[current]
        if current in positions:
            cycle = chain[positions[current]:]
            parents[min(cycle)] = None
            for index in cycle:
                issues[index] = 'cycle'
        visited.update(chain)

    children = defaultdict(list)
    roots = []
    for index, parent in enumerate(parents):
        (roots if parent is None else children[parent]).append(index)
    result = []
    seen = set()
    for root in roots:
        root_id = copies[root].get('id') if issues[root] != 'duplicate-id' else None
        pending = [root]
        while pending:
            index = pending.pop()
            if index in seen:
                raise ValueError('Review thread relationships remained cyclic.')
            seen.add(index)
            row = copies[index]
            row['replyDepth'] = 1 if index != root or issues[index] == 'missing-parent' else 0
            row['threadRoot'] = None if issues[root] == 'missing-parent' else root_id
            if issues[index]:
                row['replyIssue'] = issues[index]
            else:
                row.pop('replyIssue', None)
            result.append(row)
            pending.extend(reversed(children[index]))
    if len(result) != len(rows):
        raise ValueError('Review thread layout omitted a provider row.')
    return result
