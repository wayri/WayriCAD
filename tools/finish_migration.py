"""One-time source migration helpers for the WayriCAD 3 release."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    for path in (ROOT / "embed_3d_plugin").rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".md", ".html", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        # Machine library names must not inherit whitespace from the display name.
        text = text.replace("WayriCAD Embed3D_", "WayriCAD_Embed3D_")
        if "tests" in path.parts:
            text = text.replace("ROOT/'embed_3d_plugin/", "ROOT/'")
        if path.name == "__init__.py":
            text = text.replace("__version__ = '0.4.1'", "__version__ = '3.0.0'")
        text = text.replace('(generator_version "0.4.1")', '(generator_version "3.0.0")')
        path.write_text(text, encoding="utf-8")
    for path in ROOT.glob("*/help.html"):
        text = path.read_text(encoding="utf-8")
        if "WayriCAD" not in text:
            path.write_text(text.replace("<h1>", "<h1>WayriCAD "), encoding="utf-8")


if __name__ == "__main__":
    main()
