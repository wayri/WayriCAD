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


def render_extract_workspace() -> None:
    image = Image.new("RGB", (1200, 680), "#e9edf1")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((22, 18, 1178, 660), radius=6, fill="#ffffff", outline="#7e8c99", width=2)
    draw.rectangle((22, 18, 1178, 70), fill="#17324d")
    text(draw, (45, 33), "KiWay Pin Extractor", 24, True, "#ffffff")

    tabs = ("1  Extract Pins", "2  Signal Flow", "3  IC Signal Chart", "4  Block Diagrams")
    x = 42
    for index, label in enumerate(tabs):
        width = (190, 180, 205, 205)[index]
        fill = "#ffffff" if index == 0 else "#e5eaf0"
        draw.rectangle((x, 82, x + width, 120), fill=fill, outline="#8796a3")
        text(draw, (x + 12, 92), label, 16, index == 0, "#17324d")
        x += width

    text(draw, (42, 136), "Select on the PCB, enter wildcard filters, or combine both. Preview before export.", 16, fill="#35566f")
    draw.rounded_rectangle((42, 169, 1156, 350), radius=4, fill="#f8fafb", outline="#a9b5bf")
    text(draw, (58, 181), "1. Choose components", 17, True, "#17324d")
    for idx, label in enumerate(("PCB selection", "Wildcard filters", "Selection + filters")):
        cx = 78 + idx * 145
        draw.ellipse((cx, 218, cx + 16, 234), fill="#1769aa" if idx == 2 else "#ffffff", outline="#617685", width=2)
        text(draw, (cx + 24, 216), label, 14)
    draw.rectangle((58, 250, 520, 330), fill="#ffffff", outline="#a7b3bd")
    text(draw, (70, 259), "Selection basket", 14, True, "#17324d")
    text(draw, (72, 291), "J3    Backplane", 14)
    text(draw, (270, 291), "U1    STM32H7", 14)
    draw.rectangle((548, 207, 1137, 330), fill="#ffffff", outline="#a7b3bd")
    text(draw, (562, 217), "Wildcard filters (* and ?)", 14, True, "#17324d")
    for y, label, value in ((249, "References", "J*, U1"), (282, "Net names", "CAN_*, 28V*")):
        text(draw, (564, y + 5), label, 14)
        draw.rounded_rectangle((690, y, 1118, y + 29), radius=3, fill="#ffffff", outline="#94a3af")
        text(draw, (701, y + 5), value, 14)

    draw.rounded_rectangle((42, 365, 1156, 562), radius=4, fill="#ffffff", outline="#a9b5bf")
    text(draw, (58, 377), "2. Review extracted pins", 17, True, "#17324d")
    button(draw, (935, 375, 1135, 414), "Preview Extraction", primary=True)
    columns = (("Reference", 130), ("Value", 210), ("Pad", 100), ("Net", 350), ("Type", 160))
    left, y, x = 58, 426, 58
    for label, width in columns:
        draw.rectangle((x, y, x + width, y + 34), fill="#e7eef4", outline="#a7b3bd")
        text(draw, (x + 8, y + 7), label, 14, True, "#17324d")
        x += width
    rows = (("J3", "Backplane", "17", "CAN_A_H", "signal"), ("U1", "STM32H7", "12", "3V3", "supply"))
    for row_index, row in enumerate(rows):
        x = left
        for value, (_label, width) in zip(row, columns):
            draw.rectangle((x, y + 34 + row_index * 34, x + width, y + 68 + row_index * 34), fill="#ffffff" if row_index == 0 else "#f5f7f9", outline="#c3ccd4")
            text(draw, (x + 8, y + 41 + row_index * 34), value, 14)
            x += width
    text(draw, (58, 536), "Double-click a row to select its footprint and highlight its net on the PCB.", 14, fill="#35566f")
    text(draw, (42, 589), "3. Export the reviewed rows", 17, True, "#17324d")
    button(draw, (308, 579, 498, 622), "Export Preview...")
    button(draw, (514, 579, 730, 622), "Export Unique Nets...")
    callout(draw, 1, (920, 145), (395, 226), "Combined input")
    callout(draw, 2, (805, 350), (1005, 395), "Preview exact rows")
    callout(draw, 3, (790, 635), (405, 601), "Export only the preview")
    image.save(ROOT / "extract_pins_plugin" / "help-workflow.png", optimize=True)


def render_extract_diagrams() -> None:
    image = Image.new("RGB", (1200, 680), "#e9edf1")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((22, 18, 1178, 660), radius=6, fill="#ffffff", outline="#7e8c99", width=2)
    draw.rectangle((22, 18, 1178, 70), fill="#17324d")
    text(draw, (45, 33), "KiWay Pin Extractor - Block Diagrams", 24, True, "#ffffff")
    draw.rounded_rectangle((42, 91, 1156, 188), radius=4, fill="#f8fafb", outline="#a9b5bf")
    text(draw, (58, 103), "Diagram scope", 17, True, "#17324d")
    text(draw, (58, 144), "Components", 14)
    draw.rounded_rectangle((160, 136, 510, 167), radius=3, fill="#ffffff", outline="#94a3af")
    text(draw, (171, 142), "J*, U*", 14)
    for idx, label in enumerate(("Combined", "Signals only", "Power only")):
        x = 570 + idx * 145
        draw.ellipse((x, 141, x + 16, 157), fill="#1769aa" if idx == 0 else "#ffffff", outline="#617685", width=2)
        text(draw, (x + 23, 139), label, 14)
    button(draw, (58, 204, 270, 244), "Refresh Visual Preview", primary=True)
    button(draw, (286, 204, 496, 244), "Use Extraction Preview")
    button(draw, (512, 204, 690, 244), "Export This SVG...")

    draw.rectangle((42, 263, 1156, 608), fill="#15191f", outline="#7e8c99")
    text(draw, (58, 276), "Combined power and signal connections", 18, True, "#ffffff")
    nodes = ((90, 355, 240, 440, "J3", "Backplane"), (480, 320, 650, 480, "U1", "STM32H7"), (900, 355, 1050, 440, "J7", "Payload"))
    for x1, y1, x2, y2, ref, value in nodes:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=5, fill="#20344d", outline="#57c5b6", width=2)
        text(draw, (x1 + 15, y1 + 18), ref, 18, True, "#ffffff")
        text(draw, (x1 + 15, y1 + 49), value, 14, fill="#c5d0da")
    for y, color, label in ((360, "#00d9ff", "CAN_A_H"), (392, "#00d9ff", "CAN_A_L"), (424, "#ff6b6b", "28V_MAIN")):
        draw.line((240, y, 480, y), fill=color, width=4)
        draw.line((650, y, 900, y), fill=color, width=4)
        text(draw, (310, y - 23), label, 13, True, "#ffffff")
    text(draw, (58, 624), "Preview is embedded in the plugin; mode changes filter the visual before SVG export.", 15, fill="#35566f")
    image.save(ROOT / "extract_pins_plugin" / "help-diagrams.png", optimize=True)


def render_dependency_manager() -> None:
    image = Image.new("RGB", (1200, 680), "#e9edf1")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 24, 1172, 650), radius=7, fill="#ffffff", outline="#8a98a6", width=2)
    draw.rectangle((28, 24, 1172, 80), fill="#17324d")
    text(draw, (52, 39), "KiWay Suite Dependency Manager", 25, True, "#ffffff")
    text(draw, (52, 102), "Python 3.11.5 | KiCad 10 bundled runtime", 18, True, "#17324d")
    text(draw, (52, 132), r"User site: Documents\KiCad\10.0\3rdparty\Python311\site-packages", 16, fill="#35566f")

    text(draw, (52, 178), "Python Dependencies", 19, True, "#17324d")
    columns = ("Dependency", "Status", "Version", "Level", "Features")
    rows = (
        ("networkx", "available", "3.4", "required", "Graphs and tracing"),
        ("Markdown", "missing", "-", "recommended", "Full HTML reports"),
        ("matplotlib", "available", "3.9", "optional", "Native charts"),
        ("Pillow", "available", "11.0", "optional", "Help validation"),
    )
    widths = (160, 120, 100, 135, 405)
    left, top = 52, 214
    x = left
    for label, width in zip(columns, widths):
        draw.rectangle((x, top, x + width, top + 38), fill="#e7eef4", outline="#a7b3bd")
        text(draw, (x + 8, top + 8), label, 15, True, "#17324d")
        x += width
    for row_index, row in enumerate(rows):
        y = top + 38 + row_index * 37
        x = left
        for value, width in zip(row, widths):
            fill = "#fff7e6" if row[1] == "missing" else ("#ffffff" if row_index % 2 == 0 else "#f5f7f9")
            draw.rectangle((x, y, x + width, y + 37), fill=fill, outline="#c3ccd4")
            text(draw, (x + 8, y + 8), value, 14)
            x += width

    text(draw, (52, 424), "KiWay Plugin Packages", 19, True, "#17324d")
    text(draw, (52, 458), "9 of 9 packages installed | metadata and versions readable", 16, fill="#35566f")
    button(draw, (568, 535, 742, 583), "Check Again")
    button(draw, (756, 535, 962, 583), "Install Recommended", primary=True)
    button(draw, (976, 535, 1128, 583), "Install Selected")
    text(draw, (52, 611), "Installs into KiCad's user-site. Restart PCB Editor after installation.", 16, fill="#35566f")
    callout(draw, 1, (930, 118), (690, 118), "Verify the target runtime")
    callout(draw, 2, (900, 290), (820, 306), "See feature impact")
    callout(draw, 3, (725, 622), (850, 559), "Review before installing")
    image.save(ROOT / "extract_pins_plugin" / "help-dependencies.png", optimize=True)


if __name__ == "__main__":
    for package_name, plugin_spec in SPECS.items():
        if package_name != "extract_pins_plugin":
            render(package_name, plugin_spec)
    render_extract_workspace()
    render_extract_diagrams()
    render_dependency_manager()
