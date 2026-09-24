"""Small, deterministic summary for the native harness review header."""

from __future__ import annotations

from typing import Any, Iterable


def overview_state(records: Iterable[Any], links: Iterable[Any], system_paths: Iterable[Any]) -> dict[str, Any]:
    records = list(records)
    links = list(links)
    system_paths = list(system_paths)
    projects = {str(record.project) for record in records}
    connectors = {(str(record.project), str(record.connector)) for record in records}
    unresolved = sum(str(getattr(link, "status", "")).lower() not in ("linked", "") for link in links)
    if not records:
        next_step = "Import pin documents"
        stage = 0
    elif not links:
        next_step = "Map connector pins and build"
        stage = 1
    elif unresolved:
        next_step = "Review unresolved wires"
        stage = 2
    else:
        next_step = "Review draft and export"
        stage = 3
    return {
        "projects": len(projects),
        "connectors": len(connectors),
        "wires": len(links),
        "paths": len(system_paths),
        "unresolved": unresolved,
        "stage": stage,
        "next_step": next_step,
    }
