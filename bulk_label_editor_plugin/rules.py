"""Compiled text rules and conservative batch validation, without GUI imports."""
from __future__ import annotations

import re


def compile_rule(pattern, replacement, *, regex=False, case_sensitive=False):
    """Compile once per preview; an empty find rule is never a write operation.

    Wildcards match the whole field. Each * or ? in the replacement consumes
    the next capture of the same kind. Regex mode uses Python's group syntax.
    """
    if not pattern:
        raise ValueError("Enter a find rule before previewing changes.")
    if "\x00" in pattern or "\x00" in replacement:
        raise ValueError("Text cannot contain NUL characters.")
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        expression = re.compile(pattern, flags)
        # Validate replacement references even when there are no matching rows.
        try:
            expression.sub(replacement, "")
        except (re.error, IndexError) as exc:
            raise ValueError("Invalid regex replacement: " + str(exc)) from exc
        return lambda text: expression.sub(replacement, text)
    tokens = [char for char in pattern if char in "*?"]
    expression = re.compile("^" + "".join(
        "(.*)" if char == "*" else "(.)" if char == "?" else re.escape(char)
        for char in pattern) + "$", flags)

    def replace(text):
        match = expression.fullmatch(text)
        if match is None:
            return text
        values = {token: iter([value for kind, value in zip(tokens, match.groups())
                              if kind == token]) for token in "*?"}
        return "".join(next(values[char], char) if char in values else char
                       for char in replacement)
    return replace


def validate_changes(items, changes, *, allowed_reference_counts=None):
    """Reject blank text and reference collisions using the entire final board.

    ``items`` are current editable objects; changes are (item, old, new).
    This does not rename electrical nets or update a schematic.
    """
    changed = {id(item): new for item, _old, new in changes}
    for item, _old, new in changes:
        if not new.strip() or any(char in new for char in "\x00\r\n"):
            raise ValueError("Replacement text must be nonempty and on one line.")
        if item.kind == "Reference" and any(char.isspace() for char in new):
            raise ValueError("Footprint references cannot contain whitespace.")
    refs = {}
    for item in items:
        if item.kind != "Reference":
            continue
        value = changed.get(id(item), item.current)
        refs.setdefault(value.casefold(), []).append(item)
    for values in refs.values():
        if len(values) > 1 and any(id(item) in changed for item in values):
            final_name = changed.get(id(values[0]), values[0].current).casefold()
            if allowed_reference_counts and len(values) <= allowed_reference_counts.get(final_name, 0):
                continue
            raise ValueError("Duplicate footprint reference: " + changed.get(id(values[0]), values[0].current))


def apply_reviewed(changes, *, reverse=False, verify=None):
    """Check all old values before writing, verify readback, and roll back errors."""
    steps = [(item, new if reverse else old, old if reverse else new)
             for item, old, new in changes]
    for item, expected, _value in steps:
        if item.getter() != expected:
            raise ValueError("Text changed since review. Refresh and review again.")
    completed = []
    try:
        for item, expected, value in steps:
            completed.append((item, expected))
            item.setter(value)
            if item.getter() != value:
                raise RuntimeError("KiCad did not confirm a text update.")
        if verify is not None:
            verify([(item, value) for item, _expected, value in steps])
    except Exception as cause:
        failures = []
        for item, value in reversed(completed):
            try:
                item.setter(value)
                if item.getter() != value:
                    raise RuntimeError("Restored text was not confirmed.")
            except Exception as exc:
                failures.append(str(exc))
        if verify is not None:
            try:
                verify(completed)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError("Edit failed; recovery incomplete: " + "; ".join(failures)) from cause
        raise
