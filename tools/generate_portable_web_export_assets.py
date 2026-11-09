"""Generate deterministic Portable Web Export icons and annotated help visual."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "portable_web_export_plugin"
FONT = Path("C:/Windows/Fonts/segoeui.ttf")
BOLD = Path("C:/Windows/Fonts/seguisb.ttf")


def _font(size, bold=False):
    return ImageFont.truetype(str(BOLD if bold else FONT), size)


def make_icon(theme="light"):
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ink = "#304654" if theme == "light" else "#e6eef4"
    paper = "#f8fbfd" if theme == "light" else "#334551"
    accent = "#238c78"
    draw.rounded_rectangle((12, 18, 84, 76), radius=5, fill=paper, outline=ink, width=3)
    draw.rectangle((12, 18, 84, 31), fill="#dce9ef" if theme == "light" else "#526775", outline=ink, width=2)
    for x in (20, 27, 34):
        draw.ellipse((x - 2, 23, x + 2, 27), fill=accent)
    draw.rectangle((19, 39, 48, 68), fill="#e7f2ef" if theme == "light" else "#294e48", outline=accent, width=2)
    draw.line((25, 48, 42, 48, 42, 61, 29, 61), fill=accent, width=3)
    draw.rectangle((56, 40, 77, 47), fill=ink)
    draw.rectangle((56, 53, 77, 60), fill=accent)
    draw.rectangle((56, 66, 70, 70), fill=ink)
    return image


def make_help():
    image = Image.new("RGB", (1200, 680), "#e9edf1")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 20, 1176, 660), radius=7, fill="#ffffff", outline="#82919d", width=2)
    draw.rectangle((24, 20, 1176, 76), fill="#17324d")
    draw.text((48, 36), "WayriCAD Portable Web Export", font=_font(24, True), fill="white")
    draw.text((940, 38), "Help", font=_font(17, True), fill="white")
    draw.rounded_rectangle((46, 96, 1152, 152), radius=4, fill="#f7f9fb", outline="#b5c0c9")
    draw.text((62, 108), "Project source", font=_font(16, True), fill="#17324d")
    draw.text((62, 130), "C:/Projects/Example/controller.kicad_pcb", font=_font(15), fill="#3d5364")
    draw.rounded_rectangle((46, 172, 520, 540), radius=4, fill="#f8fafb", outline="#aebac3")
    draw.text((62, 188), "Views and design data", font=_font(17, True), fill="#17324d")
    options = ("✓  Schematic", "✓  PCB Layout", "✓  BoM and tracking", "✓  3D and models")
    for index, value in enumerate(options):
        draw.text((72, 224 + index * 34), value, font=_font(16), fill="#253746")
    draw.text((62, 370), "Schematic sheets", font=_font(16, True), fill="#17324d")
    for index, value in enumerate(("✓ controller.kicad_sch", "✓ power.kicad_sch", "✓ io.kicad_sch")):
        draw.text((76, 402 + index * 31), value, font=_font(15), fill="#385064")
    draw.rounded_rectangle((540, 172, 1152, 540), radius=4, fill="#ffffff", outline="#aebac3")
    draw.rectangle((540, 172, 730, 214), fill="#dcecff", outline="#8fa5b7")
    draw.rectangle((730, 172, 950, 214), fill="#eef1f4", outline="#8fa5b7")
    draw.text((562, 184), "Preflight", font=_font(16, True), fill="#17324d")
    draw.text((752, 184), "Web page preview", font=_font(16, True), fill="#17324d")
    rows = (("Ready", "KiCad WebView 0.1.0-beta.2"), ("Info", "3 sheets · 42 references"), ("Warning", "1 STEP model uses a proxy"))
    for index, (severity, value) in enumerate(rows):
        y = 240 + index * 52
        draw.rectangle((560, y, 1132, y + 44), fill="#f7f9fb", outline="#c1cad2")
        draw.text((574, y + 11), severity, font=_font(14, True), fill="#238c78" if severity == "Ready" else "#a56817")
        draw.text((680, y + 11), value, font=_font(14), fill="#253746")
    draw.text((560, 410), "Expected HTML size: approximately 8.6 MiB", font=_font(17, True), fill="#17324d")
    draw.rounded_rectangle((560, 459, 805, 505), radius=4, fill="#1769aa", outline="#1769aa")
    draw.text((584, 472), "Build Exact Web Preview", font=_font(16, True), fill="white")
    draw.rounded_rectangle((882, 572, 1148, 622), radius=4, fill="#238c78", outline="#238c78")
    draw.text((915, 586), "Export Offline HTML", font=_font(17, True), fill="white")
    callouts = ((1, (250, 120), (400, 120), "Confirm project"), (2, (430, 285), (500, 285), "Choose exact content"),
                (3, (1000, 258), (1130, 258), "Resolve findings"), (4, (790, 482), (805, 482), "Preview exact page"),
                (5, (820, 597), (882, 597), "Export reviewed file"))
    for number, center, target, label in callouts:
        draw.line((*center, *target), fill="#b33d2e", width=3)
        draw.ellipse((center[0]-16, center[1]-16, center[0]+16, center[1]+16), fill="#b33d2e")
        draw.text((center[0]-5, center[1]-11), str(number), font=_font(17, True), fill="white")
        draw.text((center[0]+22, center[1]-11), label, font=_font(15, True), fill="#8f2f22")
    image.save(PACKAGE / "help-workflow.png", optimize=True)


def make_page_preview():
    image = Image.new("RGB", (1200, 680), "#eef2f5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1200, 74), fill="#17324d")
    draw.text((32, 18), "Example Controller Review", font=_font(25, True), fill="white")
    draw.text((884, 17), "Revision 7d2a91c4", font=_font(14, True), fill="#d9e8f2")
    draw.text((884, 41), "2026-11-09 12:30:00 UTC", font=_font(13), fill="#c6d7e2")
    tabs = ((32, "Schematic"), (178, "PCB"), (262, "3D"), (338, "BoM & Tracking"))
    for index, (x, label) in enumerate(tabs):
        width = 136 if index == 0 else (164 if index == 3 else 74)
        fill = "#238c78" if index == 0 else "#dfe7ec"
        text_fill = "white" if index == 0 else "#253746"
        draw.rounded_rectangle((x, 88, x + width, 128), radius=4, fill=fill, outline="#94a4b0")
        draw.text((x + 15, 99), label, font=_font(15, index == 0), fill=text_fill)
    draw.rounded_rectangle((24, 146, 852, 642), radius=5, fill="white", outline="#9dabb5")
    draw.text((48, 166), "controller.kicad_sch", font=_font(17, True), fill="#17324d")
    blocks = ((74, 232, 260, 350, "U1  Controller", "STM32 / GPIO"),
              (350, 196, 548, 294, "J1  Debug", "SWD + UART"),
              (350, 388, 548, 486, "U3  Sensor", "I2C peripheral"),
              (638, 270, 806, 410, "J2  Harness", "20 positions"))
    for x1, y1, x2, y2, title, subtitle in blocks:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=5, fill="#f7fafb", outline="#3f718f", width=2)
        draw.text((x1 + 14, y1 + 18), title, font=_font(16, True), fill="#17324d")
        draw.text((x1 + 14, y1 + 48), subtitle, font=_font(14), fill="#526878")
    links = (((260, 264, 350, 242), "#238c78", "SWDIO", (286, 238)),
             ((260, 304, 638, 318), "#237bb0", "UART3_TX", (430, 292)),
             ((260, 332, 350, 430), "#a56817", "I2C1_SDA", (286, 368)),
             ((548, 438, 638, 370), "#a56817", "SENSOR_INT", (552, 394)))
    for points, color, label, pos in links:
        draw.line(points, fill=color, width=4)
        draw.text(pos, label, font=_font(12, True), fill=color)
    draw.rounded_rectangle((874, 146, 1176, 642), radius=5, fill="white", outline="#9dabb5")
    draw.text((898, 166), "Review status", font=_font(18, True), fill="#17324d")
    rows = (("Selected", "U1", "#238c78"), ("Ordered", "18 / 42", "#237bb0"),
            ("Received", "12 / 42", "#a56817"), ("Assembly", "In progress", "#7b5aa6"))
    for index, (label, value, color) in enumerate(rows):
        y = 214 + index * 68
        draw.rectangle((898, y, 1150, y + 52), fill="#f6f8fa", outline="#c5ced5")
        draw.ellipse((910, y + 17, 928, y + 35), fill=color)
        draw.text((940, y + 7), label, font=_font(13, True), fill="#304654")
        draw.text((940, y + 27), value, font=_font(14), fill="#17202a")
    draw.line((898, 514, 1150, 514), fill="#c5ced5", width=1)
    draw.text((898, 532), "Traceability", font=_font(16, True), fill="#17324d")
    draw.text((898, 562), "Document  4b91f0e8", font=_font(13), fill="#385064")
    draw.text((898, 586), "Project     15ac74d2", font=_font(13), fill="#385064")
    draw.text((898, 610), "Sources     6 verified", font=_font(13), fill="#385064")
    image.save(PACKAGE / "help-page-preview.png", optimize=True)


def main():
    PACKAGE.mkdir(exist_ok=True)
    light = make_icon("light")
    light.resize((64, 64), Image.Resampling.LANCZOS).save(PACKAGE / "icon.png", optimize=True)
    resources = PACKAGE / "resources"
    resources.mkdir(exist_ok=True)
    for theme in ("light", "dark"):
        source = make_icon(theme)
        for size in (24, 48, 96):
            suffix = "-dark" if theme == "dark" else ""
            source.resize((size, size), Image.Resampling.LANCZOS).save(resources / f"icon{suffix}-{size}.png", optimize=True)
    make_help()
    make_page_preview()


if __name__ == "__main__":
    main()
