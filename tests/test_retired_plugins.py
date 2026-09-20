"""Retired tools must not reappear in active installs or advertised capabilities."""
from pathlib import Path

from build_pcm import discover_plugins
from extract_pins_plugin.automation import capabilities
from tools.install_suite import retire_plugins, RETIRED_PLUGINS
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_visual_diff_is_retained_only_as_archived_source():
    retired = ROOT / 'visual_diff_plugin'
    assert (retired / 'metadata.legacy.json').is_file()
    assert (retired / 'plugin.legacy.json').is_file()
    assert not (retired / 'metadata.json').exists()
    assert not (retired / 'plugin.json').exists()
    assert retired not in discover_plugins(ROOT)
    assert len(discover_plugins(ROOT)) == 16
    advertised = capabilities()
    assert 'visual-diff' not in advertised['additional_cli']
    assert not any(p['id'] == 'visual-diff' for p in advertised['plugins'])


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


@pytest.mark.parametrize('folder,retired_id,replacement,nested', [
    ('pdn_decoupling_plugin','pdn-decoupling','quick_pi_plugin','decoupling'),
    ('return_path_auditor_plugin','return-path-auditor','signal_integrity_advisor_plugin','return_path'),
    ('test_point_descriptor_plugin','test-points','signal_integrity_advisor_plugin','test_points'),
    ('variant_workbench_plugin','variant-workbench',None,None),
])
def test_consolidated_plugins_are_archived_and_replacements_are_installable(folder,retired_id,replacement,nested):
    retired=ROOT/folder
    assert (retired/'metadata.legacy.json').is_file()
    assert (retired/'plugin.legacy.json').is_file()
    assert not (retired/'metadata.json').exists()
    assert not (retired/'plugin.json').exists()
    assert retired not in discover_plugins(ROOT)
    assert 'com.github.wayri.wayricad.'+retired_id in RETIRED_PLUGINS
    assert all(p['id'] != retired_id for p in capabilities()['plugins'])
    if replacement:
        target=ROOT/replacement
        assert target in discover_plugins(ROOT)
        for asset in ('__init__.py','help.html','help-workflow.png','icon.png'):
            assert (target/nested/asset).is_file()
        assert 'register' not in (target/nested/'__init__.py').read_text(encoding='utf-8')
