"""Optional native KiCad 10 action; comparison always reads saved design files."""
from pathlib import Path
import pcbnew


class VisualDiffPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "WayriCAD Visual Diff"
        self.category = "Review"
        self.description = "Compare saved PCB or schematic revisions in a local visual report"
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).parent / "resources" / "icon-24.png")
        self.dark_icon_file_name = str(Path(__file__).parent / "resources" / "icon-dark-24.png")

    def Run(self):
        from .kicad_vizdiff.desktop import show
        board = pcbnew.GetBoard()
        show(board.GetFileName() if board else "")
