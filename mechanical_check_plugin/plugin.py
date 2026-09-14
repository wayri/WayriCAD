"""Optional native KiCad 10 action; the PCM package also has an IPC launcher."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
try:
    import pcbnew
except ImportError:
    pcbnew = None

if pcbnew is not None:
    class MechanicalCheckPlugin(pcbnew.ActionPlugin):
        def defaults(self):
            self.name = 'WayriCAD Mechanical Check'
            self.category = 'Mechanical validation'
            self.description = 'Review saved-board fit, hardware and model coverage'
            self.show_toolbar_button = True
            root = Path(__file__).resolve().parent
            self.icon_file_name = str(root / 'resources/icon-24.png')
            self.dark_icon_file_name = str(root / 'resources/icon-dark-24.png')

        def Run(self):
            from wayricad_mechanical.ui import Window
            board = pcbnew.GetBoard()
            path = board.GetFileName() if board else None
            self.window = Window(board_path=path)
            self.window.Show()


