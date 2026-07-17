"""Local documentation generation for KiWay extraction outputs."""

from __future__ import annotations

import csv
import html
import os
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional, Sequence


TYPE_LABELS = {
    "TM": "Telemetry",
    "TC": "Telecommand",
    "TA": "Telemetry Analog",
    "TD": "Telemetry Digital",
    "CA": "Command Analog",
    "CD": "Command Digital",
}


class DocGenerator:
    """Generate Markdown, HTML, and CSV artifacts for software/test teams."""

    def __init__(self, title: str = "KiWay Interface Control Document") -> None:
        self.title = title

    def build_markdown(
        self,
        tm_tc_rows: Sequence[Dict[str, Any]] = (),
        test_point_rows: Sequence[Dict[str, Any]] = (),
        interface_maps: Optional[Dict[str, Dict[str, Any]]] = None,
        connector_rows: Sequence[Dict[str, Any]] = (),
        peripheral_rows: Sequence[Dict[str, Any]] = (),
        flow_rows: Sequence[Dict[str, Any]] = (),
    ) -> str:
        lines = [f"# {self.title}", ""]
        lines.extend(self._table_section("Telemetry / Telecommand Map", list(tm_tc_rows)))
        lines.extend(self._table_section("Test Points", list(test_point_rows)))
        lines.extend(self._table_section("Signal Flow", list(flow_rows)))
        lines.extend(self._interface_section(interface_maps or {}))
        lines.extend(self._table_section("Connectors", list(connector_rows)))
        lines.extend(self._table_section("Peripherals", list(peripheral_rows)))
        return "\n".join(lines).strip() + "\n"

    def export_markdown(self, markdown_text: str, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
        return path

    def export_html(self, markdown_text: str, path: str) -> str:
        try:
            import markdown
        except ImportError:
            body = self._basic_markdown_to_html(markdown_text)
        else:
            body = markdown.markdown(markdown_text, extensions=["tables", "toc"])

        css = """
body { font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #202124; }
h1, h2, h3 { color: #17324d; }
table { border-collapse: collapse; width: 100%; margin: 12px 0 28px; font-size: 13px; }
th, td { border: 1px solid #d6dde5; padding: 7px 9px; text-align: left; vertical-align: top; }
th { background: #eef3f8; }
tr:nth-child(even) td { background: #fafbfd; }
code { background: #f2f4f7; padding: 1px 4px; border-radius: 3px; }
"""
        html_doc = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_doc)
        return path

    def export_csv(self, rows: Sequence[Dict[str, Any]], path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        headers = self._headers(rows)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({h: row.get(h, "") for h in headers})
        return path

    def make_tm_tc_rows(self, parser: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for net_name, pins in sorted(parser.net_to_pins.items(), key=lambda item: parser.natural_sort_key(item[0])):
            parsed = parser.parse_interface_label(net_name)
            if not parsed.tm_tc_type:
                continue
            for ref, pin in pins:
                rows.append(
                    {
                        "Type": parsed.tm_tc_type,
                        "Type Label": TYPE_LABELS.get(parsed.tm_tc_type, parsed.tm_tc_type),
                        "Source Board": parsed.source_board,
                        "Destination Board": parsed.destination_board,
                        "Interface": parsed.interface,
                        "Signal": parsed.signal,
                        "Channel": parsed.channel,
                        "Net Name": net_name,
                        "Reference": ref,
                        "Pin": pin,
                    }
                )
        return rows

    def connector_rows_from_parser(self, parser: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for ref, meta in parser.components.items():
            if meta.get("kind") != "connector":
                continue
            for row in parser.get_component_pin_nets(ref):
                rows.append(
                    {
                        "Connector": ref,
                        "Value": meta.get("value", ""),
                        "Pin": row["pin"],
                        "Net Name": row["net"],
                    }
                )
        return rows

    def peripheral_rows_from_parser(self, parser: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for ref, meta in parser.components.items():
            if meta.get("kind") not in {"active", "component"}:
                continue
            rows.append(
                {
                    "Reference": ref,
                    "Value": meta.get("value", ""),
                    "Kind": meta.get("kind", ""),
                    "Footprint": meta.get("footprint", ""),
                }
            )
        return sorted(rows, key=lambda r: parser.natural_sort_key(r["Reference"]))

    def _interface_section(self, interface_maps: Dict[str, Dict[str, Any]]) -> List[str]:
        lines = ["## Interface Maps", ""]
        if not interface_maps:
            return lines + ["No interface maps found.", ""]
        for name, iface in sorted(interface_maps.items()):
            lines.append(f"### {name}")
            lines.append("")
            rows = [
                {
                    "Net Name": net,
                    "Source Board": iface.get("source_board", ""),
                    "Destination Board": iface.get("destination_board", ""),
                    "TM/TC Types": ", ".join(iface.get("tm_tc_types", [])),
                }
                for net in iface.get("nets", [])
            ]
            lines.extend(self._markdown_table(rows))
            lines.append("")
        return lines

    def _table_section(self, title: str, rows: List[Dict[str, Any]]) -> List[str]:
        lines = [f"## {title}", ""]
        if not rows:
            return lines + ["No entries found.", ""]
        lines.extend(self._markdown_table(rows))
        lines.append("")
        return lines

    def _markdown_table(self, rows: List[Dict[str, Any]]) -> List[str]:
        headers = self._headers(rows)
        if not headers:
            return ["No entries found."]
        lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        for row in rows:
            values = [str(row.get(h, "")).replace("|", "\\|").replace("\n", " ") for h in headers]
            lines.append("| " + " | ".join(values) + " |")
        return lines

    def _headers(self, rows: Sequence[Dict[str, Any]]) -> List[str]:
        headers: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in headers:
                    headers.append(key)
        return headers

    def _basic_markdown_to_html(self, markdown_text: str) -> str:
        lines = []
        in_table = False
        for raw in markdown_text.splitlines():
            line = raw.rstrip()
            if line.startswith("# "):
                lines.append(f"<h1>{html.escape(line[2:])}</h1>")
            elif line.startswith("## "):
                lines.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line.startswith("### "):
                lines.append(f"<h3>{html.escape(line[4:])}</h3>")
            elif line.startswith("|") and line.endswith("|"):
                cells = [html.escape(c.strip()) for c in line.strip("|").split("|")]
                if set(cells) == {"---"}:
                    continue
                tag = "th" if not in_table else "td"
                if not in_table:
                    lines.append("<table>")
                    in_table = True
                lines.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
            else:
                if in_table:
                    lines.append("</table>")
                    in_table = False
                if line:
                    lines.append(f"<p>{html.escape(line)}</p>")
        if in_table:
            lines.append("</table>")
        return "\n".join(lines)
