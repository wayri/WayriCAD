"""Pure model adapters between WayriCAD protocol detection and Constraint Studio."""
from __future__ import annotations

from collections import Counter

from .analysis import merge_managed_rules
from .constraint_studio.inspection import items_from_board, rule_match
from .constraint_studio.model import RuleDocument


def stage_protocol_rules(workspace, generated):
    """Parse before replacing the staged document; never writes project files."""
    if not generated.strip():
        raise ValueError("Preview protocol rules before staging them.")
    document = RuleDocument.load(merge_managed_rules(workspace.document.emit(), generated))
    workspace.document = document


def overview(workspace):
    issues = workspace.issues()
    counts = Counter(issue.severity for issue in issues)
    return {
        "rules": len(workspace.document.rules),
        "enabled": sum(rule.enabled for rule in workspace.document.rules),
        "errors": counts["error"], "warnings": counts["warning"],
        "changed": sorted(workspace.changes()), "issues": issues,
    }


def scope_preview(workspace, rule_index, items=None):
    """Preview the condition on each saved item, not effective DRC constraints.

    A/B conditions retain unknown results when the second object is unavailable.
    Counts describe these condition results only, never violations or coverage.
    """
    items = items if items is not None else items_from_board(workspace.context, workspace.project)
    if rule_index is None:
        return [(item, None, ["Select a rule to preview its condition."]) for item in items]
    rule = workspace.document.rules[rule_index]
    result = []
    for item in items:
        match = rule_match(rule, item, context=workspace.context)
        result.append((item, match.value, match.reasons))
    return result
