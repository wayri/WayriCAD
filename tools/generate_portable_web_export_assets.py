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


if __name__ == "__main__":
    main()
