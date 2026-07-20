from __future__ import annotations

import unittest

from extract_pins_plugin.core.doc_generator import DocGenerator


class ReportRenderingTests(unittest.TestCase):
    def test_preview_html_has_explicit_theme_safe_table_colors(self) -> None:
        html = DocGenerator().render_html(
            "# Report\n\n| Net | Long Path |\n|---|---|\n| GND | /Root/Power/Channel/Feedback |\n",
            for_preview=True,
        )

        self.assertIn("background: #ffffff", html)
        self.assertIn("color: #202124", html)
        self.assertIn("table-layout: fixed", html)
        self.assertIn("overflow-wrap: anywhere", html)
        self.assertIn("name='viewport'", html)

    def test_export_and_preview_use_different_margins(self) -> None:
        generator = DocGenerator()
        self.assertIn("margin: 12px", generator.render_html("# Preview", for_preview=True))
        self.assertIn("margin: 28px", generator.render_html("# Export"))


if __name__ == "__main__":
    unittest.main()
