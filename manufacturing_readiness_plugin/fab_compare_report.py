"""Canonical, source-bound exports for imported fabrication net comparisons."""
from __future__ import annotations

import copy
import csv
import datetime as dt
import hashlib
import io
import json
from html import escape
from pathlib import Path


SCHEMA = "wayricad.fab-net-compare-report/v1"
NOTICE = ("Imported netlist comparison only. No Gerber copper reconstruction or physical "
          "fabrication approval is performed. Missing/unsupported coverage and self-comparison "
          "cannot establish an independent CAM match.")
MAX_SOURCE_BYTES = 64 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def source_snapshot(path, role):
    """Fingerprint one stable saved input, retaining the selected symlink identity."""
    selected = Path(path).absolute()
    resolved = selected.resolve(strict=True)
    before = resolved.stat()
    if not resolved.is_file() or before.st_size > MAX_SOURCE_BYTES:
        raise ValueError("Choose an input file no larger than 64 MiB.")
    with resolved.open("rb") as stream:
        data = stream.read(MAX_SOURCE_BYTES+1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeded the 64 MiB snapshot budget while reading.")
    after = resolved.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Source changed while being read; compare again.")
    return dict(role=role, path=str(resolved), selected_path=str(selected), bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(), modified_ns=after.st_mtime_ns,
                modified_at=dt.datetime.fromtimestamp(after.st_mtime, dt.timezone.utc).isoformat())


def assert_sources_current(sources):
    if not sources:
        raise ValueError("Source provenance is missing; compare again.")
    for source in sources:
        current = source_snapshot(source.get("selected_path", source["path"]), source["role"])
        if current != source:
            raise ValueError("Source changed since comparison: "+Path(source["path"]).name)


def _report_hash(report):
    payload = copy.deepcopy(report)
    payload["report_metadata"].pop("sha256", None)
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def build_report(comparison, *, sources, board_path=None):
    """Keep the core's complete verdict/findings; add reproducible evidence metadata."""
    if (not isinstance(comparison, dict) or comparison.get("schema") != "wayricad.fab-compare/v1"
            or comparison.get("status") not in ("MATCH", "FAIL", "UNKNOWN")
            or comparison.get("fabrication_verified") is not False):
        raise ValueError("The comparison must supply its own explicit status.")
    assert_sources_current(sources)
    for side in ("reference", "observed"):
        selected = [source for source in sources if source["role"].lower().startswith(side)
                    or side == "observed" and source["role"].lower() == "cam"]
        if len(selected) != 1 or comparison.get("sources", {}).get(side, {}).get("sha256") != selected[0]["sha256"]:
            raise ValueError("Parsed "+side+" bytes do not match the selected source snapshot.")
    report = copy.deepcopy(comparison)
    report["report_metadata"] = dict(schema=SCHEMA, generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        sources=copy.deepcopy(sources), board_context=str(Path(board_path).resolve()) if board_path else None,
        notice=NOTICE)
    report["report_metadata"]["sha256"] = _report_hash(report)
    return report


def validate_report(report, *, check_sources=True):
    metadata = report.get("report_metadata", {})
    if metadata.get("schema") != SCHEMA or metadata.get("sha256") != _report_hash(report):
        raise ValueError("Report contents changed; compare again before export.")
    if check_sources:
        assert_sources_current(metadata.get("sources"))


def _text(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else _json(value)


def report_rows(report, *, limit=None):
    """One stable row per core finding; details always retain the complete record."""
    rows = []
    groups = [("SHORT", report.get("shorts", [])), ("OPEN", report.get("opens", []))]
    coverage = report.get("coverage", {})
    for field, kind in (("missing_pins", "MISSING"), ("extra_pins", "EXTRA")):
        if coverage.get(field):
            groups.append((kind, [dict(endpoints=coverage[field], message=kind+" endpoint coverage")]))
    groups.append(("ISSUE", report.get("issues", [])))
    for kind, findings in groups:
        for index, finding in enumerate(findings):
            if limit is not None and len(rows) >= limit:
                return rows
            detail = finding if isinstance(finding, dict) else {"value": finding}
            identifier = str(detail.get("id") or hashlib.sha256(
                (kind+"\0"+str(index)+"\0"+_json(detail)).encode()).hexdigest()[:16])
            names = lambda value: "; ".join(map(str, value)) if isinstance(value, list) else _text(value)
            endpoints = detail.get("endpoints", [])
            pins = "; ".join(str(pin.get("reference", ""))+"."+str(pin.get("pin", ""))
                             for pin in endpoints if isinstance(pin, dict))
            rows.append(dict(kind=kind, id=identifier,
                reference_nets=names(detail.get("design_nets", detail.get("design_net"))),
                observed_nets=names(detail.get("observed_nets", detail.get("observed_net"))),
                pins=pins,
                message=str(detail.get("message", detail.get("description", kind+" finding"))),
                details=copy.deepcopy(detail)))
    return rows


def render_report(report, format):
    validate_report(report, check_sources=False)
    format = format.lower().lstrip(".")
    if format == "json":
        return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n"
    rows = report_rows(report)
    metadata = report["report_metadata"]
    basis = {key: report.get(key) for key in ("sources", "independence", "reference_binding", "fabrication_verified", "limits")}
    if format == "txt":
        summary = report.get("summary", {})
        parts = ["Fabrication Net Comparison", "Status: "+report["status"], NOTICE,
                 "Generated UTC: "+metadata["generated_at"], "Report SHA-256: "+metadata["sha256"],
                 "Total net compare errors: "+str(summary.get("short_groups", 0)+summary.get("open_groups", 0)),
                 "Short groups: "+str(summary.get("short_groups", 0)),
                 "Open groups: "+str(summary.get("open_groups", 0)),
                 "Matched pins: "+str(summary.get("matched_pins", 0)),
                 "Missing pins: "+str(summary.get("missing_pins", 0)),
                 "Extra pins: "+str(summary.get("extra_pins", 0)),
                 "Complete endpoint coverage: "+str(summary.get("complete", False)), "", "Shorts in Job"]
        parts.insert(4, "Reference binding: "+str(report.get("reference_binding", {}).get("status", "UNVERIFIED")))
        pins = lambda endpoints: ", ".join(str(p["reference"])+"."+str(p["pin"]) for p in endpoints)
        for index, finding in enumerate(report.get("shorts", []), 1):
            parts.append(f"{index}. CAM net {finding['observed_net']} joins {len(finding['design_groups'])} design nets:")
            for group in finding["design_groups"]:
                parts.append("   "+str(group["name"])+": "+pins(group["endpoints"]))
        if not report.get("shorts"):
            parts.append("None proven on shared endpoints.")
        parts += ["", "Opens in Job"]
        for index, finding in enumerate(report.get("opens", []), 1):
            parts.append(f"{index}. Design net {finding['design_net']} splits into {len(finding['observed_groups'])} CAM groups:")
            for group in finding["observed_groups"]:
                parts.append("   "+str(group["name"])+": "+pins(group["endpoints"]))
        if not report.get("opens"):
            parts.append("None proven on shared endpoints.")
        parts += ["", "Coverage and issues"]
        for key in ("missing_pins", "extra_pins"):
            if report.get("coverage", {}).get(key):
                parts.append(key.replace("_", " ")+": "+pins(report["coverage"][key]))
        for issue in report.get("issues", []):
            parts.append(str(issue.get("side", "comparison"))+" / "+str(issue.get("code", "issue"))+": "+str(issue.get("message", "")))
        parts += ["", "Source identity"]
        for source in metadata["sources"]:
            parts += [source["role"]+": "+source["path"], "   SHA-256 "+source["sha256"]+
                      "; bytes "+str(source["bytes"])+"; modified UTC "+source["modified_at"]]
        parts += ["", "Comparison limits", *[str(limit) for limit in report.get("limits", [])],
                  "Full structured evidence and pin maps are retained in the JSON export."]
        return "\n".join(parts)+"\n"
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["kind", "identity", "reference_nets", "cam_nets", "pins", "details_json",
                         "comparison_status", "report_sha256", "generated_at", "coverage_json", "sources_json", "basis_json", "notice"])
        # Prefix spreadsheet formula triggers; JSON remains the exact evidence.
        def cell(value):
            value = str(value)
            return "'"+value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")) else value
        for row in rows or [dict(kind="SUMMARY", id="", reference_nets="", observed_nets="", pins="", details={})]:
            writer.writerow([cell(value) for value in (row["kind"], row["id"], row["reference_nets"], row["observed_nets"],
                row["pins"], _json(row["details"]), report["status"], metadata["sha256"], metadata["generated_at"],
                _json(report.get("coverage", {})), _json(metadata["sources"]), _json(basis), NOTICE)])
        return stream.getvalue()
    if format not in ("html", "htm"):
        raise ValueError("Choose JSON, HTML, CSV or TXT.")
    e = lambda value: escape(_text(value), quote=True)
    document = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; '
        'connect-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">'
        '<title>Fabrication Net Comparison</title><style>'
        'body{font:14px/1.5 system-ui,sans-serif;color:#20282b;margin:24px auto;padding:0 16px;max-width:1200px}'
        'h1{font-size:24px}h2{font-size:18px}table{border-collapse:collapse;width:100%}'
        'th,td{padding:8px;border:1px solid #cad0d2;text-align:left;vertical-align:top}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere}td{overflow-wrap:anywhere}section{overflow:auto}'
        '</style></head><body><h1>Fabrication Net Comparison</h1><p><strong>Status: '+e(report["status"])+
        '</strong></p><p>'+e(NOTICE)+'</p><p>Generated UTC: '+e(metadata["generated_at"])+
        '</p><p>Report SHA-256: '+e(metadata["sha256"])+
        '</p><h2>Summary</h2><pre>'+e(report.get("summary", {}))+'</pre><h2>Coverage</h2><pre>'+
        e(report.get("coverage", {}))+'</pre><section><table><thead><tr><th>Type</th><th>Identity</th>'
        '<th>Reference nets</th><th>CAM nets</th><th>Pins</th><th>Full net / pin mapping</th></tr></thead><tbody>')
    for row in rows:
        document += '<tr>'+''.join('<td>'+e(row[key])+'</td>' for key in
            ("kind", "id", "reference_nets", "observed_nets", "pins"))+ '<td><pre>'+e(row["details"])+'</pre></td></tr>'
    document += ('</tbody></table></section><h2>Comparison basis</h2><pre>'+e(basis)+
        '</pre><h2>Source identity</h2><pre>'+e(metadata)+
        '</pre><h2>Core provenance</h2><pre>'+e(report.get("provenance", {}))+'</pre></body></html>')
    return document


def export_report(report, destination, *, format=None, protected_sources=()):
    """Publish one format atomically; never overwrite any input or board context."""
    destination = Path(destination)
    format = (format or destination.suffix.lstrip(".")).lower().lstrip(".")
    if destination.suffix.lower().lstrip(".") not in ("json", "html", "htm", "csv", "txt"):
        raise ValueError("Choose a JSON, HTML, CSV or TXT report destination.")
    normalized = lambda value: "html" if value == "htm" else value
    if normalized(format) != normalized(destination.suffix.lower().lstrip(".")):
        raise ValueError("Report format must match the destination extension.")
    validate_report(report)
    content = render_report(report, format)
    metadata = report["report_metadata"]
    sources = [source["path"] for source in metadata["sources"]]
    if metadata.get("board_context"):
        board = Path(metadata["board_context"])
        sources += [board.with_suffix(suffix) for suffix in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".kicad_sch")]
    sources.extend(protected_sources)
    try:
        from .wayricad_runtime.report_ui import publish_documents
    except ModuleNotFoundError as exc:
        if exc.name != __package__+".wayricad_runtime":
            raise
        from wayricad_runtime.report_ui import publish_documents
    publish_documents({destination: content}, sources=sources, source_guard=lambda: validate_report(report))
    return destination
