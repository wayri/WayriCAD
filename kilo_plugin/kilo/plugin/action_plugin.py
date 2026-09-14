"""KiCad PCB Action Plugin entry."""

from __future__ import annotations

from pathlib import Path

from kilo.identity import PRODUCT_TITLE

try:
    import pcbnew  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - standalone runtime
    pcbnew = None  # type: ignore[assignment]


if pcbnew is not None:

    class KiloActionPlugin(pcbnew.ActionPlugin):  # type: ignore[misc]
        def defaults(self) -> None:
            self.name = PRODUCT_TITLE
            self.category = "Project Dependencies"
            self.description = "Package design blocks and localize project footprints/models"
            self.icon_file_name = str(Path(__file__).resolve().parents[2] / "resources" / "icon-24.png")
            self.dark_icon_file_name = self.icon_file_name.replace("icon-24.png", "icon-dark-24.png")
            self.show_toolbar_button = True

        def Run(self) -> None:
            from kilo.ui.main_frame import launch

            launch()


    def register() -> None:
        KiloActionPlugin().register()

else:

    def register() -> None:
        return
