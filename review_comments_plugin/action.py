"""Lazy IPC action; no native registration or comment retrieval during import."""
from pathlib import Path
import pcbnew


class ReviewPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'WayriCAD Review'
        self.category = 'Review'
        self.description = 'GitHub and GitLab comments for the saved design revision'
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).parent / 'icon.png')
        self.dark_icon_file_name = str(Path(__file__).parent / 'resources' / 'icon-dark-48.png')

    def Run(self):
        from wayricad_runtime.context import saved_board
        from .conversation_ui import ConversationPane
        ConversationPane(saved_board()).Show()
