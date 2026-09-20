"""Retired installations are migrated without deleting user settings."""
from tools.install_suite import retire_plugins, RETIRED_PLUGINS


def test_retired_installs_are_previewed_then_backed_up_without_loss(tmp_path):
    destination = tmp_path / 'plugins'
    names = tuple(name for identifier in RETIRED_PLUGINS for name in (identifier, identifier.replace('.', '_')))
    for name in names:
        folder = destination / name
        folder.mkdir(parents=True)
        (folder / 'user-settings.json').write_bytes(b'{"custom":true}')
    active = destination / 'com.github.wayri.wayricad.extract-pins'
    active.mkdir()
    assert retire_plugins(destination) == []
    assert all((destination / name).is_dir() for name in names)
    moved = retire_plugins(destination, apply=True)
    assert len(moved) == len(names)
    assert all(not (destination / name).exists() for name in names)
    assert all((path / 'user-settings.json').read_bytes() == b'{"custom":true}' for path in moved)
    assert active.is_dir()
    assert retire_plugins(destination, apply=True) == []
