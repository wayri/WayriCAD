"""Generate deterministic annotated UI walkthroughs for KiWay help pages."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = Path("C:/Windows/Fonts/segoeui.ttf")
BOLD_PATH = Path("C:/Windows/Fonts/seguisb.ttf")

SPECS = {
    "bulk_label_editor_plugin": ("Bulk Label Editor", ("Configure", "Review preview", "Apply"), ("Find: CH*_MAIN", "Replace: CH*_REDUNDANT", "Scope: references, values, fields"), ("Kind", "Owner", "Current", "New"), (("Reference", "J4", "CH1_MAIN", "CH1_REDUNDANT"), ("Field:Channel", "U2", "CH2_MAIN", "CH2_REDUNDANT")), "Preview Changes", "Apply Preview"),
    "connector_icd_plugin": ("Connector ICD Builder", ("Load", "Review on PCB", "Export"), ("Board: active PCB", "Detection: J*, P*, CN*, CONN, HEADER"), ("Connector", "Part", "Pin", "Net"), (("J1", "Backplane", "12", "CAN_A_H"), ("J1", "Backplane", "13", "CAN_A_L")), "Refresh Preview", "Export CSV"),
    "extract_pins_plugin": ("Extract Pins and Build ICD", ("Configure", "Preview and review", "Export"), ("Netlist directory: project/xml", "Board order: DEMO_CTRL, DEMO_SENSOR, DEMO_POWER, DEMO_IO", "Advanced filters: collapsed"), ("Reference", "Pad", "Net", "Type"), (("J3", "17", "DEMO_CTRL_DEMO_SENSOR_SPI_CLK_TD", "signal"), ("TP12", "1", "3V3", "supply")), "Analyze & Preview", "Export..."),
    "fanout_generator_plugin": ("Fanout Generator", ("Configure", "Window preview", "PCB preview", "Commit"), ("Footprint: U7", "Pattern: BGA/LGA Grid Escape", "Width: 0.20 mm   Length: 1.50 mm"), ("Footprint", "Pad", "Net", "Result"), (("U7", "A1", "DDR_DQ0", "Track + via"), ("U7", "A2", "DDR_DQ1", "Track + via")), "Preview in Window", "Show on PCB", "Commit to PCB"),
    "net_hygiene_plugin": ("Net Hygiene", ("Scan", "Inspect", "Export"), ("Board: active PCB", "Preview: errors and warnings"), ("Severity", "Kind", "Object", "Details"), (("error", "duplicate-reference", "R17", "Two footprints"), ("warning", "single-pad-net", "TEST_CLK", "U2.7")), "Scan Preview", "Export CSV"),
    "test_coverage_plugin": ("Test Coverage Planner", ("Scan", "Inspect gaps", "Export"), ("Detection: TP* or TestPoint value", "Focus: missing access"), ("Net", "Test Points", "Status", "Count"), (("SPI_CLK", "TP17", "Covered", "1"), ("RESET_N", "", "Missing", "0")), "Scan Preview", "Export CSV"),
    "test_point_descriptor_plugin": ("Test Point Descriptor Extractor", ("Configure", "Review preview", "Export"), ("Descriptor field: TP_Descriptor", "Board order: DEMO_CTRL, DEMO_SENSOR, DEMO_POWER, DEMO_IO"), ("TP", "Net", "Type", "Destination"), (("TP10", "SPI_CLK", "TD", "DEMO_SENSOR"), ("TP11", "RESET_N", "CD", "DEMO_POWER")), "Extract Preview", "Export..."),
    "trace_impedance_plugin": ("Trace RLC / Impedance Analyzer", ("Configure path", "Review result", "Export"), ("Net: USB_D+", "Start: J2.3   End: U4.17", "Frequency: 480 MHz   Reference: GND plane"), ("Metric", "Value", "Metric", "Value"), (("Length", "42.18 mm", "Vias", "2"), ("Impedance", "48.7 ohm", "Delay", "284 ps")), "Analyze Path", "Export CSV"),
    "via_stitching_plugin": ("Via Stitching", ("Configure", "Window preview", "PCB preview", "Commit"), ("Net: GND", "Spacing: 2.50 mm   Edge inset: 1.00 mm", "Area and exclusions: optional"), ("#", "Net", "X (mm)", "Y (mm)"), (("1", "GND", "12.500", "8.000"), ("2", "GND", "15.000", "8.000")), "Preview in Window", "Show on PCB", "Commit to PCB"),
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD_PATH if bold else FONT_PATH), size)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int = 18, bold: bool = False, fill: str = "#202124") -> None:
    draw.text(xy, value, font=font(size, bold), fill=fill)


def button(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, primary: bool = False) -> None:
    fill, outline = ("#1769aa", "#1769aa") if primary else ("#ffffff", "#82909c")
    foreground = "#ffffff" if primary else "#17324d"
    draw.rounded_rectangle(box, radius=4, fill=fill, outline=outline, width=2)
    bounds = draw.textbbox((0, 0), label, font=font(17, True))
    x = box[0] + (box[2] - box[0] - (bounds[2] - bounds[0])) // 2
    y = box[1] + (box[3] - box[1] - (bounds[3] - bounds[1])) // 2 - 1
    text(draw, (x, y), label, 17, True, foreground)


def callout(draw: ImageDraw.ImageDraw, number: int, center: tuple[int, int], target: tuple[int, int], label: str) -> None:
    draw.line((center, target), fill="#c34a36", width=3)
    draw.ellipse((center[0] - 17, center[1] - 17, center[0] + 17, center[1] + 17), fill="#c34a36")
    text(draw, (center[0] - 5, center[1] - 11), str(number), 18, True, "#ffffff")
    text(draw, (center[0] + 25, center[1] - 12), label, 17, True, "#8f2f22")


def render(package: str, spec: tuple) -> None:
    title, steps, controls, columns, rows, primary, secondary, *remaining = spec
    image = Image.new("RGB", (1200, 680), "#e9edf1")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 24, 1172, 650), radius=7, fill="#ffffff", outline="#8a98a6", width=2)
    draw.rectangle((28, 24, 1172, 80), fill="#17324d")
    text(draw, (52, 39), f"KiWay {title}", 25, True, "#ffffff")
    for index, step in enumerate(steps):
        x = 52 + index * 270
        fill = "#d9eaff" if index == 1 else "#eef1f4"
        draw.rounded_rectangle((x, 100, x + 238, 142), radius=4, fill=fill, outline="#8ca3b5")
        text(draw, (x + 13, 111), f"{index + 1}  {step}", 17, True, "#17324d")
    draw.rounded_rectangle((52, 166, 1148, 282), radius=4, fill="#f8fafb", outline="#c4cdd5")
    text(draw, (70, 179), "Settings", 18, True, "#17324d")
    for index, control in enumerate(controls):
        y = 211 + (index % 2) * 38
        x = 70 + (index // 2) * 530
        draw.rounded_rectangle((x, y, x + 500, y + 30), radius=3, fill="#ffffff", outline="#a8b3bd")
        text(draw, (x + 10, y + 5), control, 15)
    text(draw, (52, 305), "Preview", 19, True, "#17324d")
    if remaining:
        draw.rectangle((52, 340, 548, 500), fill="#f7f9fb", outline="#a7b3bd")
        for x in range(72, 548, 40):
            draw.line((x, 340, x, 500), fill="#d7dfe6", width=1)
        for y in range(360, 500, 40):
            draw.line((52, y, 548, y), fill="#d7dfe6", width=1)
        for start, end in (((170, 430), (245, 385)), ((235, 440), (315, 390)), ((300, 440), (390, 405))):
            draw.line((*start, *end), fill="#1769aa", width=4)
            draw.ellipse((end[0] - 6, end[1] - 6, end[0] + 6, end[1] + 6), fill="#f2a38f", outline="#9b3527", width=2)
        text(draw, (67, 474), "In-window geometry: no PCB changes", 14, True, "#35566f")
        left, top, width = 570, 340, 578
    else:
        left, top, width = 52, 340, 1096
    column_width = width // len(columns)
    for index, column in enumerate(columns):
        x = left + index * column_width
        draw.rectangle((x, top, x + column_width, top + 38), fill="#e7eef4", outline="#a7b3bd")
        text(draw, (x + 9, top + 8), column, 15, True, "#17324d")
    for row_index, row in enumerate(rows):
        y = top + 38 + row_index * 42
        fill = "#ffffff" if row_index % 2 == 0 else "#f5f7f9"
        for index, value in enumerate(row):
            x = left + index * column_width
            draw.rectangle((x, y, x + column_width, y + 42), fill=fill, outline="#c3ccd4")
            text(draw, (x + 7, y + 10), value, 14)
    if remaining:
        button(draw, (565, 544, 755, 592), primary, primary=True)
        button(draw, (770, 544, 935, 592), secondary)
        button(draw, (950, 544, 1128, 592), remaining[0])
    else:
        button(draw, (700, 544, 880, 592), primary, primary=True)
        button(draw, (896, 544, 1068, 592), secondary)
        button(draw, (1080, 544, 1148, 592), "Help")
    text(draw, (52, 609), "Next: inspect the preview and highlighted PCB objects before committing or exporting.", 16, fill="#35566f")
    callout(draw, 1, (900, 118), (760, 121), "Follow the visible steps")
    callout(draw, 2, (354, 317), (354, 341), "Preview is evidence")
    callout(draw, 3, (835, 622), (740 if remaining else 790, 568), "Primary action")
    image.save(ROOT / package / "help-workflow.png", optimize=True)


if __name__ == "__main__":
    for package_name, plugin_spec in SPECS.items():
        render(package_name, plugin_spec)
