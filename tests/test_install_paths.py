from pathlib import Path
import json
import sys
import zipfile

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


def test_existing_pcm_install_takes_precedence_over_direct_copy(tmp_path):
    destination = tmp_path / "KiCad" / "10.0" / "plugins"
    identifier = "com.github.wayri.wayricad.quick-pi"
    direct = destination / identifier
    direct.mkdir(parents=True)
    pcm = destination.parent / "3rdparty" / "plugins" / identifier.replace(".", "_")
    assert install_suite.installation_target(destination, identifier) == direct

    pcm.mkdir(parents=True)
    (pcm / "plugin.json").write_text(json.dumps({"identifier": identifier}), encoding="utf-8")
    assert install_suite.installation_target(destination, identifier) == pcm


def test_pcm_install_must_match_expected_identifier(tmp_path):
    destination = tmp_path / "KiCad" / "10.0" / "plugins"
    identifier = "com.github.wayri.wayricad.quick-pi"
    pcm = destination.parent / "3rdparty" / "plugins" / identifier.replace(".", "_")
    pcm.mkdir(parents=True)
    (pcm / "plugin.json").write_text(json.dumps({"identifier": "other.plugin.id"}), encoding="utf-8")
    try:
        install_suite.installation_target(destination, identifier)
    except ValueError as exc:
        assert "Unexpected PCM plugin" in str(exc)
    else:
        raise AssertionError("A mismatched PCM install was accepted")


def test_disposable_archive_updates_pcm_copy_with_backup(tmp_path, monkeypatch):
    identifier = "com.github.wayri.wayricad.sample"
    source = tmp_path / "source"
    plugin = source / "sample_plugin"
    plugin.mkdir(parents=True)
    (plugin / "metadata.json").write_text(json.dumps({"versions": [{"version": "3.3.0"}]}), encoding="utf-8")
    archives = tmp_path / "archives"
    archives.mkdir()
    package = archives / "WayriCAD-sample-3.3.0-PCM.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("plugins/plugin.json", json.dumps({"identifier": identifier, "name": "Sample"}))
        archive.writestr("plugins/entrypoint.py", "new source")

    destination = tmp_path / "KiCad" / "10.0" / "plugins"
    pcm = destination.parent / "3rdparty" / "plugins" / identifier.replace(".", "_")
    pcm.mkdir(parents=True)
    (pcm / "plugin.json").write_text(json.dumps({"identifier": identifier}), encoding="utf-8")
    (pcm / "entrypoint.py").write_text("old source", encoding="utf-8")

    monkeypatch.setattr(install_suite, "ROOT", source)
    monkeypatch.setattr(sys, "argv", ["install_suite.py", "--destination", str(destination),
                                   "--archive-dir", str(archives), "--apply"])
    install_suite.main()

    assert (pcm / "entrypoint.py").read_text(encoding="utf-8") == "new source"
    assert not (destination / identifier).exists()
    backups = list((destination.parent / "wayricad-plugin-backups").glob(identifier + "-*"))
    assert len(backups) == 1
    assert (backups[0] / "entrypoint.py").read_text(encoding="utf-8") == "old source"
