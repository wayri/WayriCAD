"""Generate the light, legible Signal Integrity Advisor icon."""

from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
path = root / "signal_integrity_advisor_plugin" / "icon.png"
image = Image.new("RGBA", (128, 128), "#f7fbfd")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 120, 120), radius=12, fill="#ffffff", outline="#98adba", width=4)
draw.line((18, 72, 34, 72, 42, 44, 54, 96, 66, 56, 78, 72, 110, 72), fill="#167a9d", width=7, joint="curve")
draw.line((18, 34, 110, 34), fill="#e29b35", width=5)
draw.ellipse((92, 18, 116, 42), fill="#ffffff", outline="#276f43", width=4)
draw.line((98, 30, 104, 36, 114, 23), fill="#276f43", width=4)
image.save(path, optimize=True)
