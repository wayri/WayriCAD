"""Generate the complete, size-consistent KiWay PCM and toolbar icon set."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SPECS = {
    "bulk_label_editor_plugin": ("#247ba0", "labels"),
    "extract_pins_plugin": ("#17806d", "extract"),
    "fanout_generator_plugin": ("#c66a1b", "fanout"),
    "harness_workbench_plugin": ("#2e8b57", "harness"),
    "heater_designer_plugin": ("#c74f3d", "heater"),
    "kilo_plugin": ("#3b6ea8", "localize"),
    "manufacturing_readiness_plugin": ("#d9822b", "factory"),
    "pdn_decoupling_plugin": ("#c23b53", "pdn"),
    "planar_magnetics_plugin": ("#3d6591", "magnetics"),
    "portable_assets_plugin": ("#417f62", "portable"),
    "protocol_constraint_composer_plugin": ("#6b5ca5", "rules"),
    "return_path_auditor_plugin": ("#1f77b4", "return"),
    "signal_integrity_advisor_plugin": ("#00838f", "signal"),
    "test_point_descriptor_plugin": ("#a23c64", "probe"),
    "trace_impedance_plugin": ("#536d9c", "impedance"),
    "variant_workbench_plugin": ("#7b6d3d", "variants"),
    "via_stitching_plugin": ("#397a9b", "stitch"),
}


def icon(color: str, kind: str) -> Image.Image:
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    dark = "#40515f"
    pale = "#edf3f7"
    draw.rounded_rectangle((6, 6, 89, 89), radius=7, fill="#ffffff", outline="#aebdca", width=2)

    if kind == "labels":
        for y in (25, 43, 61):
            draw.rounded_rectangle((17, y - 6, 64, y + 6), radius=2, fill=pale, outline=dark, width=2)
            draw.line((25, y, 53, y), fill=color, width=3)
        draw.line((57, 70, 77, 50), fill=color, width=7)
        draw.polygon(((74, 47), (82, 55), (78, 59), (70, 51)), fill=dark)
    elif kind == "extract":
        draw.rectangle((20, 22, 54, 74), fill=pale, outline=dark, width=3)
        for y in (30, 42, 54, 66):
            draw.line((14, y, 20, y), fill=color, width=3)
            draw.line((54, y, 61, y), fill=color, width=3)
        draw.line((62, 48, 78, 48), fill=color, width=5)
        draw.polygon(((78, 39), (87, 48), (78, 57)), fill=color)
    elif kind == "fanout":
        draw.rounded_rectangle((31, 31, 65, 65), radius=4, fill="#f2d6b6", outline=dark, width=3)
        for x, y, ex, ey in ((31,35,17,22),(31,48,14,48),(31,61,17,74),(65,35,79,22),(65,48,82,48),(65,61,79,74)):
            draw.line((x, y, ex, ey), fill=color, width=3)
            draw.ellipse((ex - 4, ey - 4, ex + 4, ey + 4), fill=color)
    elif kind == "harness":
        for y, bend in ((27, 0), (45, 7), (63, -6)):
            draw.line((20, y, 46, y, 76, y + bend), fill=color, width=4)
        draw.rectangle((14, 20, 22, 70), fill=pale, outline=dark, width=2)
        draw.rectangle((74, 20, 82, 70), fill=pale, outline=dark, width=2)
    elif kind == "heater":
        draw.rectangle((16, 18, 80, 78), fill="#fff6f2", outline=dark, width=2)
        points = [(23, 27), (72, 27), (72, 38), (23, 38), (23, 49), (72, 49), (72, 60), (23, 60), (23, 69), (72, 69)]
        draw.line(points, fill=color, width=5, joint="curve")
        draw.ellipse((41, 40, 55, 54), fill="#f5b642", outline="#b65a27", width=2)
    elif kind == "localize":
        draw.rounded_rectangle((16, 27, 59, 70), radius=3, fill=pale, outline=dark, width=3)
        draw.polygon(((16, 27), (30, 27), (35, 34), (59, 34), (59, 27)), fill="#d9e8f4", outline=dark)
        draw.ellipse((54, 47, 69, 62), outline=color, width=4)
        draw.ellipse((67, 47, 82, 62), outline=color, width=4)
    elif kind == "factory":
        draw.rectangle((17, 43, 79, 75), fill=pale, outline=color, width=3)
        draw.polygon(((17,43),(17,27),(35,39),(35,25),(53,39),(53,43)), fill="#ffffff", outline=color)
        draw.rectangle((62, 20, 72, 43), fill=color)
        draw.line((27,56,68,56),fill=dark,width=3)
    elif kind == "pdn":
        draw.line((18, 30, 78, 30), fill=color, width=6)
        draw.line((48, 30, 48, 68), fill=color, width=5)
        for x in (31, 57):
            draw.line((x - 7, 54, x + 7, 54), fill=dark, width=3)
            draw.line((x - 7, 63, x + 7, 63), fill=dark, width=3)
    elif kind == "magnetics":
        for inset in (0, 8, 16):
            draw.rounded_rectangle((17 + inset, 17 + inset, 79 - inset, 79 - inset), radius=8, outline=color, width=4)
        draw.ellipse((42, 42, 54, 54), fill="#ffffff", outline=dark, width=3)
        draw.line((48, 12, 48, 25), fill=dark, width=3)
        draw.polygon(((43, 17), (53, 17), (48, 9)), fill=dark)
    elif kind == "portable":
        draw.rounded_rectangle((15, 24, 62, 70), radius=3, fill=pale, outline=dark, width=3)
        draw.polygon(((15,24),(30,24),(35,31),(62,31),(62,24)), fill="#dcece4", outline=dark)
        draw.polygon(((55,48),(69,40),(82,48),(68,56)), fill="#ffffff", outline=color)
        draw.polygon(((55,48),(68,56),(68,74),(55,66)), fill="#dcece4", outline=color)
        draw.polygon(((68,56),(82,48),(82,66),(68,74)), fill="#c5dfd1", outline=color)
    elif kind == "rules":
        draw.rectangle((19, 17, 77, 77), fill=pale, outline=color, width=3)
        for y in (31, 47, 63):
            draw.ellipse((27, y - 4, 35, y + 4), fill=color)
            draw.line((42, y, 68, y), fill=dark, width=3)
    elif kind == "return":
        draw.line((18, 28, 54, 28, 54, 66, 78, 66), fill=color, width=6)
        draw.line((18, 68, 42, 68, 42, 42, 70, 42), fill=dark, width=4)
        draw.ellipse((48, 60, 60, 72), fill="#ffffff", outline=color, width=3)
    elif kind == "signal":
        points = ((14, 50), (25, 50), (32, 29), (43, 68), (53, 38), (63, 55), (82, 55))
        draw.line(points, fill=color, width=5, joint="curve")
        draw.line((17, 74, 79, 74), fill=dark, width=2)
    elif kind == "probe":
        draw.ellipse((18, 48, 44, 74), fill=pale, outline=color, width=4)
        draw.ellipse((26, 56, 36, 66), fill=color)
        draw.line((38, 54, 68, 24), fill=dark, width=7)
        draw.polygon(((67, 19), (78, 30), (70, 34), (63, 27)), fill=color)
    elif kind == "impedance":
        draw.line((16, 58, 27, 58, 34, 36, 44, 70, 54, 42, 63, 58, 80, 58), fill=color, width=4)
        draw.line((20, 25, 73, 25), fill=dark, width=3)
        draw.line((20, 76, 73, 76), fill=dark, width=3)
        draw.text((68, 33), "Z", fill=dark, stroke_width=1)
    elif kind == "variants":
        draw.line((22, 24, 22, 72), fill=dark, width=4)
        for y, target in ((28, 47), (48, 65), (68, 47)):
            draw.line((22, y, target, y), fill=color, width=4)
            draw.ellipse((target - 5, y - 5, target + 5, y + 5), fill="#ffffff", outline=color, width=3)
        draw.line((62, 63, 68, 69, 80, 54), fill=color, width=4)
    else:  # stitch
        for x in (25, 48, 71):
            for y in (25, 48, 71):
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color, outline=dark)
        draw.line((21, 48, 75, 48), fill=dark, width=3)
        draw.line((48, 21, 48, 75), fill=dark, width=3)

    return image


def main() -> None:
    for folder, (color, kind) in SPECS.items():
        generated = icon(color, kind)
        generated.save(ROOT / folder / "icon.png", optimize=True)
        if folder == "kilo_plugin":
            generated.save(ROOT / folder / "kilo" / "icon.png", optimize=True)


if __name__ == "__main__":
    main()
