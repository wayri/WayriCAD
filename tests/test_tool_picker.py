"""Installed-tool search must find Review without loading arbitrary manifests."""
import json

import pytest

from wayricad_runtime.tool_picker import installed_desktop_tools, text_colours


def package(parent, identifier='com.github.wayri.wayricad.review-comments', name='WayriCAD Review'):
    plugin = parent / identifier
    plugin.mkdir(parents=True)
    (plugin / 'plugin.json').write_text(json.dumps(dict(identifier=identifier, actions=[dict(
        name=name, scopes=['pcb'], entrypoint='ipc_entrypoint.py')])))
    (plugin / 'desktop_entrypoint.py').write_text('raise RuntimeError("Discovery must not execute code")')
    return plugin


def test_pcm_picker_discovers_review_installed_in_user_directory(tmp_path):
    root = tmp_path/'10.0/3rdparty/plugins/com_github_wayri_wayricad_bom-studio'
    root.mkdir(parents=True)
    review = package(tmp_path/'10.0/plugins')
    assert installed_desktop_tools(root) == {'WayriCAD Review': (review, 'review-comments')}


def test_user_picker_discovers_pcm_peer_and_prefers_its_own_root(tmp_path):
    root = package(tmp_path/'10.0/plugins')
    package(tmp_path/'10.0/3rdparty/plugins')
    assert installed_desktop_tools(root) == {'WayriCAD Review': (root, 'review-comments')}


def test_emerge_literal_desktop_entrypoint_is_discoverable(tmp_path):
    root=package(tmp_path/'10.0/plugins','com.github.wayri.wayricad.quick-emerge','Quick EMerge (beta)')
    manifest=root/'plugin.json';data=json.loads(manifest.read_text())
    data['actions'][0]['entrypoint']='desktop_entrypoint.py';manifest.write_text(json.dumps(data))
    assert installed_desktop_tools(root)=={'Quick EMerge (beta)':(root,'quick-emerge')}


@pytest.mark.parametrize('change', ['foreign', 'unsupported', 'folder', 'outside-entrypoint', 'missing-launcher', 'bad-json'])
def test_untrusted_or_incomplete_manifest_is_not_launchable(tmp_path, change):
    root=tmp_path/'10.0/plugins/caller';root.mkdir(parents=True)
    plugin=package(root.parent)
    manifest=plugin/'plugin.json';data=json.loads(manifest.read_text())
    if change=='foreign':data['identifier']='com.other.review-comments'
    elif change=='unsupported':data['identifier']='com.github.wayri.wayricad.unknown'
    elif change=='folder':plugin.rename(plugin.parent/'unrelated-folder')
    elif change=='outside-entrypoint':data['actions'][0]['entrypoint']='../other.py'
    elif change=='missing-launcher':(plugin/'desktop_entrypoint.py').unlink()
    if change!='folder':manifest.write_text('{bad' if change=='bad-json' else json.dumps(data))
    assert installed_desktop_tools(root)=={}


@pytest.mark.parametrize('dark', [False,True])
def test_selected_foreground_and_background_have_high_contrast(dark):
    def luminance(colour):
        channels=[int(colour[i:i+2],16)/255 for i in (1,3,5)]
        return sum(weight*(c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4)
                   for c,weight in zip(channels,[.2126,.7152,.0722]))
    for selected in (False,True):
        fg,bg=map(luminance,text_colours(selected,dark))
        assert (max(fg,bg)+.05)/(min(fg,bg)+.05)>4.5
