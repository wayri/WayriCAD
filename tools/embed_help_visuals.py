"""Embed generated walkthrough images into each standalone help page."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


for help_path in sorted(ROOT.glob("*_plugin/help.html")):
    content = help_path.read_text(encoding="utf-8")
    if "help-workflow.png" in content:
        continue
    content = content.replace(
        "</style>",
        "img.walkthrough{display:block;width:100%;height:auto;border:1px solid #b9c4cf;margin:12px 0 24px}</style>",
        1,
    )
    heading_end = content.find("</h1>")
    if heading_end < 0:
        raise ValueError(f"No h1 found in {help_path}")
    insert_at = heading_end + len("</h1>")
    visual = (
        '<h2>Annotated interface walkthrough</h2>'
        '<p>The numbered cues below match the visible workflow in the plugin. '
        'A preview is the review evidence; committing or exporting is the final step.</p>'
        '<img class="walkthrough" src="help-workflow.png" '
        'alt="Annotated KiWay interface showing workflow steps, preview area, and primary actions">'
    )
    help_path.write_text(content[:insert_at] + visual + content[insert_at:], encoding="utf-8")
