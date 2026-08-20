"""Programming/debug interface discovery and bring-up document generation."""

from __future__ import annotations

import csv
import fnmatch
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PATTERNS = {
    "SWD": ("*SWDIO*", "*SWCLK*", "*SWO*"),
    "JTAG": ("*TCK*", "*TMS*", "*TDI*", "*TDO*", "*TRST*"),
    "UART": ("*UART*", "*TXD*", "*RXD*"),
    "Reset": ("*RESET*", "*NRST*", "*RST*"),
    "Boot strap": ("*BOOT*", "*MODE*", "*STRAP*"),
    "Programming power": ("*VREF*", "*VTREF*", "*VCC*", "*3V3*", "*5V*", "*GND*"),
}


@dataclass(frozen=True)
class BringUpPin:
    interface: str
    reference: str
    pin: str
    net: str
    function: str
    direction: str
    note: str


def classify_net(net: str, patterns: dict[str, tuple[str, ...]] = DEFAULT_PATTERNS) -> str:
    return next((name for name, rules in patterns.items()
                 if any(fnmatch.fnmatchcase(net.casefold(), rule.casefold()) for rule in rules)), "")


def collect_bringup_rows(pin_rows: list[dict], reference_patterns: str = "J*,U*") -> list[BringUpPin]:
    refs = [value.strip() for value in reference_patterns.split(",") if value.strip()]
    output = []
    for row in pin_rows:
        reference = str(row.get("reference", row.get("ref", "")))
        net = str(row.get("net", row.get("net_name", "")))
        interface = classify_net(net)
        if not interface or not any(fnmatch.fnmatchcase(reference.casefold(), pattern.casefold()) for pattern in refs): continue
        function = str(row.get("function", row.get("pin_function", net)))
        upper = net.upper(); direction = "power" if any(token in upper for token in ("VCC", "VREF", "3V3", "5V", "GND")) else "bidirectional" if interface in {"SWD", "JTAG"} else "signal"
        output.append(BringUpPin(interface, reference, str(row.get("pin", row.get("pad", ""))), net, function, direction, "Verify voltage level and target-state requirements."))
    return sorted(output, key=lambda item: (item.interface, item.reference, item.pin))


def markdown(rows: list[BringUpPin]) -> str:
    lines = ["# Programming and Bring-Up Package", "", "## Interface Pins", "",
             "| Interface | Reference | Pin | Net | Function | Direction | Note |",
             "|---|---|---:|---|---|---|---|"]
    lines.extend(f"| {r.interface} | {r.reference} | {r.pin} | {r.net} | {r.function} | {r.direction} | {r.note} |" for r in rows)
    lines.extend(["", "## Bring-Up Checklist", "", "- Confirm target and debugger voltage compatibility.",
                  "- Verify reset and boot-strap states before applying power.",
                  "- Current-limit the first power application and validate rails in sequence.",
                  "- Confirm connector orientation and ground continuity before attaching the programmer.",
                  "- Record firmware image, programmer version, current draw, and observed console output.", ""])
    return "\n".join(lines)


def c_header(rows: list[BringUpPin], guard: str = "KIWAY_BRINGUP_PINS_H") -> str:
    lines = [f"#ifndef {guard}", f"#define {guard}", ""]
    seen = set()
    for row in rows:
        name = "KIWAY_" + "".join(char if char.isalnum() else "_" for char in f"{row.interface}_{row.function}").upper().strip("_")
        if name in seen: continue
        seen.add(name); lines.append(f'#define {name}_NET "{row.net}"'); lines.append(f'#define {name}_PIN "{row.reference}.{row.pin}"')
    lines.extend(["", f"#endif /* {guard} */", ""]); return "\n".join(lines)


def export_csv(path: str | Path, rows: list[BringUpPin]) -> None:
    with Path(path).open("w",newline="",encoding="utf-8") as handle:
        writer=csv.writer(handle);writer.writerow(BringUpPin.__dataclass_fields__);writer.writerows(tuple(vars(row).values()) for row in rows)
