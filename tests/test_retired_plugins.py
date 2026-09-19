"""Retired tools must not reappear in active installs or advertised capabilities."""
from pathlib import Path

from build_pcm import discover_plugins
from extract_pins_plugin.automation import capabilities
from tools.install_suite import retire_plugins


ROOT = Path(__file__).resolve().parents[1]


def test_visual_diff_is_retained_only_as_archived_source():
    retired = ROOT / 'visual_diff_plugin'
    assert (retired / 'metadata.legacy.json').is_file()
    assert (retired / 'plugin.legacy.json').is_file()
    assert not (retired / 'metadata.json').exists()
    assert not (retired / 'plugin.json').exists()
    assert retired not in discover_plugins(ROOT)
    assert len(discover_plugins(ROOT)) == 20
    advertised = capabilities()
    assert 'visual-diff' not in advertised['additional_cli']
    assert not any(p['id'] == 'visual-diff' for p in advertised['plugins'])


def test_retired_installs_are_previewed_then_backed_up_without_loss(tmp_path):
    destination = tmp_path / 'plugins'
    names = ('com.github.wayri.wayricad.visual-diff', 'com_github_wayri_wayricad_visual-diff')
    for name in names:
        folder = destination / name
        folder.mkdir(parents=True)
        (folder / 'user-settings.json').write_bytes(b'{"custom":true}')
    active = destination / 'com.github.wayri.wayricad.extract-pins'
    active.mkdir()
    assert retire_plugins(destination) == []
    assert all((destination / name).is_dir() for name in names)
    moved = retire_plugins(destination, apply=True)
    assert len(moved) == 2
    assert all(not (destination / name).exists() for name in names)
    assert all((path / 'user-settings.json').read_bytes() == b'{"custom":true}' for path in moved)
    assert active.is_dir()
    assert retire_plugins(destination, apply=True) == []
