from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from extract_pins_plugin.dependency_manager import (
    DEPENDENCIES,
    install_command,
    recommended_missing,
)


class DependencyManagerTests(unittest.TestCase):
    def test_install_command_targets_active_python_user_site(self) -> None:
        command = install_command(["markdown", "networkx"])
        self.assertEqual(command[:3], [sys.executable, "-m", "pip"])
        self.assertIn("--user", command)
        self.assertEqual(command[-2:], ["networkx>=2.8", "Markdown>=3.4"])

    def test_unknown_dependency_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown dependencies"):
            install_command(["not-a-kiway-dependency"])

    def test_recommended_missing_excludes_optional_by_default(self) -> None:
        rows = [
            {
                "key": spec.key,
                "installed": False,
                "satisfied": False,
                "level": spec.level,
            }
            for spec in DEPENDENCIES
        ]
        with patch("extract_pins_plugin.dependency_manager.inspect_dependencies", return_value=rows):
            self.assertEqual(recommended_missing(), ["networkx", "markdown"])
            self.assertEqual(recommended_missing(include_optional=True), ["networkx", "markdown", "matplotlib", "pillow"])


if __name__ == "__main__":
    unittest.main()
