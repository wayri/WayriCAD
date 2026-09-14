import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from visual_diff_plugin.kicad_vizdiff.cli import main, write_report
from visual_diff_plugin.kicad_vizdiff.desktop import command_for
from visual_diff_plugin.kicad_vizdiff.git import VizError, git, safe_path, snapshot
from visual_diff_plugin.kicad_vizdiff.render import bounds, pair_pages, render


def svg(box="0 0 200 100"):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm" viewBox="{box}"><path d="M1 1L4 4"/></svg>'


class VisualDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def repository(self):
        repo = self.root / "repo with spaces"
        repo.mkdir()
        git(repo, "init")
        (repo / "board.kicad_pcb").write_text("original", encoding="utf-8")
        (repo / "local.pretty").mkdir()
        (repo / "local.pretty" / "part.kicad_mod").write_text("footprint", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "Original")
        return repo

    def test_snapshot_preserves_libraries_and_never_checks_out(self):
        repo = self.repository()
        original = git(repo, "rev-parse", "HEAD")
        (repo / "board.kicad_pcb").write_text("edited", encoding="utf-8")
        snapshot(repo, "HEAD", self.root / "before")
        snapshot(repo, "WORKTREE", self.root / "after")
        self.assertEqual((self.root / "before/board.kicad_pcb").read_text(), "original")
        self.assertEqual((self.root / "after/board.kicad_pcb").read_text(), "edited")
        self.assertEqual((self.root / "before/local.pretty/part.kicad_mod").read_text(), "footprint")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), original)
        self.assertEqual((repo / "board.kicad_pcb").read_text(), "edited")

    def test_snapshot_deleted_and_untracked_files(self):
        repo = self.repository()
        (repo / "board.kicad_pcb").unlink()
        (repo / "new.kicad_sch").write_text("new", encoding="utf-8")
        snapshot(repo, "WORKTREE", self.root / "after")
        self.assertFalse((self.root / "after/board.kicad_pcb").exists())
        self.assertTrue((self.root / "after/new.kicad_sch").exists())

    def test_snapshot_budget(self):
        repo = self.repository()
        with self.assertRaisesRegex(VizError, "Snapshot exceeds"):
            snapshot(repo, "HEAD", self.root / "after", max_bytes=1)

    def test_reject_path_traversal(self):
        for name in ("../outside", "/absolute", ".git/config", "C:/escape", "a\\b"):
            with self.subTest(name=name), self.assertRaises(VizError):
                safe_path(self.root, name)

    def test_missing_revision_is_actionable(self):
        repo = self.repository()
        with self.assertRaises(VizError):
            snapshot(repo, "not-a-revision", self.root / "after")

    def test_bounds_reject_non_finite(self):
        for box in ("0 0 nan 1", "0 0 inf 1", "0 0 -1 2", "0 0 1", "0 0 1 0"):
            with self.subTest(box=box), self.assertRaises(VizError): bounds(svg(box))

    def test_different_page_sizes_share_union_coordinates(self):
        page = pair_pages({"page": svg()}, {"page": svg("-10 -20 300 200")})[0]
        self.assertEqual((page["width"], page["height"]), (300, 200))
        for side in ("before", "after"):
            decoded = base64.b64decode(page[side].split(",", 1)[1]).decode()
            self.assertEqual(bounds(decoded), [-10, -20, 300, 200])

    def test_added_removed_layers(self):
        pages = pair_pages({"removed": svg()}, {"added": svg()})
        self.assertEqual([p["status"] for p in pages], ["removed", "added"])
        self.assertIsNone(pages[0]["after"])
        self.assertIsNone(pages[1]["before"])

    def test_report_data_cannot_escape_script(self):
        output = self.root / "report.html"
        write_report(output, {"file": "</script><script>alert(1)</script>", "pages": []})
        text = output.read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert(1)</script>", text)
        payload = text.split('<script id="report-data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)["file"], "</script><script>alert(1)</script>")
        self.assertIn("connect-src 'none'", text)
        self.assertIn("WayriCAD Visual Diff", text)

    def test_failed_report_replace_preserves_previous_report(self):
        output = self.root / "report.html"
        output.write_text("previous", encoding="utf-8")
        with patch("visual_diff_plugin.kicad_vizdiff.cli.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(OSError): write_report(output, {})
        self.assertEqual(output.read_text(), "previous")
        self.assertEqual(list(self.root.glob(".wayricad-report-*")), [])

    def test_ui_command_keeps_arguments_separate(self):
        repo = self.repository()
        args, target = command_for(repo / "board.kicad_pcb", self.root / "my report.html", base="HEAD~1", theme="My theme")
        self.assertEqual(args[args.index("--repo") + 1], str(repo))
        self.assertEqual(args[args.index("--theme") + 1], "My theme")
        self.assertEqual(target.name, "my report.html")

    def test_ui_single_view_and_renamed_design(self):
        repo = self.repository()
        args, _ = command_for(repo / "board.kicad_pcb", self.root / "report.html", view=True)
        self.assertIn("--ref", args)
        self.assertNotIn("--base", args)
        args, _ = command_for(repo / "board.kicad_pcb", self.root / "report.html", old_file="previous.kicad_pcb")
        self.assertEqual(args[args.index("--old-file") + 1], "previous.kicad_pcb")

    def test_ui_rejects_missing_design(self):
        with self.assertRaisesRegex(VizError, "existing saved"):
            command_for(self.root / "missing.kicad_pcb", self.root / "report.html")

    def test_render_requires_produced_artifact(self):
        (self.root / "board.kicad_sch").write_text("fake", encoding="utf-8")
        with patch("visual_diff_plugin.kicad_vizdiff.render.run", return_value=b""):
            with self.assertRaisesRegex(VizError, "no SVG output"):
                render(self.root, "board.kicad_sch", self.root / "output", "kicad-cli")

    def test_doctor_rejects_older_kicad(self):
        with patch("visual_diff_plugin.kicad_vizdiff.cli.find_kicad", return_value="kicad-cli"), patch("visual_diff_plugin.kicad_vizdiff.cli.run", return_value=b"9.0.0"):
            self.assertEqual(main(["doctor"]), 1)


if __name__ == "__main__":
    unittest.main()
