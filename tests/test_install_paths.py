from pathlib import Path

from tools import install_suite


def test_linux_default_and_xdg_paths():
    home = Path.cwd() / "test-home"
    assert install_suite.default_destination("10.0", platform="linux", environ={}, home=home) == home / ".local/share/KiCad/10.0/plugins"
    data = home / "custom-data"
    assert install_suite.default_destination("10.0", platform="linux", environ={"XDG_DATA_HOME": str(data)}, home=home) == data / "KiCad/10.0/plugins"
    assert install_suite.default_destination("10.0", platform="linux", environ={"XDG_DATA_HOME": "relative"}, home=home) == home / ".local/share/KiCad/10.0/plugins"


def test_mac_and_documents_override():
    home = Path.cwd() / "test-home"
    assert install_suite.default_destination("10.0", platform="darwin", environ={}, home=home) == home / "Documents/KiCad/10.0/plugins"
    custom = home / "custom-kicad"
    for platform in ("win32", "linux", "darwin"):
        assert install_suite.default_destination("11.0", platform=platform, environ={"KICAD_DOCUMENTS_HOME": str(custom)}, home=home) == custom / "KiCad/11.0/plugins"


def test_windows_redirected_documents(monkeypatch):
    redirected = Path.cwd() / "OneDrive" / "Documents"
    monkeypatch.setattr(install_suite, "windows_documents", lambda: redirected)
    assert install_suite.default_destination("10.0", platform="win32", environ={}) == redirected / "KiCad/10.0/plugins"
