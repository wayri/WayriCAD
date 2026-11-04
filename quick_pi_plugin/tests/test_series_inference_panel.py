"""Hidden native controls exercise embedded review without opening any dialogs."""
from copy import deepcopy
import json

import pytest
from unittest.mock import patch

wx = pytest.importorskip('wx', reason='Native wx runtime required for inference panel controls')

from quick_pi_plugin.series_inference import InlineInference
from quick_pi_plugin.tests.series_inference_fixture import inventory


@pytest.fixture(scope='module')
def app():
    return wx.App.Get() or wx.App(False)


@pytest.fixture
def review(app):
    frame = wx.Frame(None)
    accepted = []
    panel = InlineInference(frame, inventory(), accepted.append)
    yield panel, accepted
    frame.Destroy()


@pytest.fixture
def editor(app, monkeypatch):
    from quick_pi_plugin.series_editor import SeriesPathDialog
    frame = wx.Frame(None)
    monkeypatch.setattr(wx, 'MessageBox', lambda *a, **k: pytest.fail('Unexpected review error: ' + str(a)))
    with patch('wx.Display') as display:
        display.GetFromWindow.return_value = 0
        display.return_value.GetClientArea.return_value = wx.Rect(0, 0, 1200, 700)
        controller = SeriesPathDialog(frame, inventory(), 'Example.kicad_pcb')
    controller.source.SetStringSelection('J1.1')
    controller.sink.SetStringSelection('J2.1')
    controller._changed()
    yield controller
    controller.dialog.Destroy()
    frame.Destroy()


def models(panel):
    for stage in panel.controls:
        for part, check, text, incoming, outgoing in stage:
            text.SetValue('100m' if part['reference'] in ('Q1', 'Q3') else '200m')


def test_panel_starts_without_inference_or_guessed_models_and_reports_errors_inline(review, monkeypatch):
    panel, accepted = review
    monkeypatch.setattr(wx, 'MessageBox', lambda *a, **k: pytest.fail('Review must remain inline'))
    assert panel.proposal is None
    assert panel.controls == []
    assert panel.infer('J1.1', 'J2.1')
    assert [len(stage) for stage in panel.controls] == [2, 2]
    assert all(not text.GetValue() for stage in panel.controls for _, _, text, _, _ in stage)
    with pytest.raises(ValueError, match='Q1'):
        panel.reviewed_path()
    assert 'Q1' in panel.status.GetLabel()
    panel._use()
    assert accepted == []
    models(panel)
    panel._use()
    assert len(accepted) == 1
    assert accepted[0]['branches'][0]['parallel'][0]['footprint_uuid'] == 'q2'


def test_route_switch_and_json_restore_preserve_models_selections_and_pin_subsets(app):
    chosen = inventory()
    for number, net in enumerate(('VIN', 'OUT'), 1):
        chosen['terminals'].append(dict(id=f'R1-{number}', label=f'R1.{number}',
            footprint_uuid='r1', reference='R1', net=net, component_value='100m'))
    frame = wx.Frame(None)
    try:
        panel = InlineInference(frame, chosen, lambda path: None)
        assert panel.infer('J1.1', 'J2.1')
        assert len(panel.proposal['routes']) > 1
        panel.routes.SetSelection(1)
        panel._populate()
        models(panel)
        panel.controls[0][0][3][0][1].SetValue(False)
        panel.controls[0][1][1].SetValue(False)
        expected = panel.reviewed_path()
        panel.routes.SetSelection(0)
        panel._populate()
        panel.controls[0][0][2].SetValue('500m')
        panel.routes.SetSelection(1)
        panel._populate()
        assert panel.reviewed_path() == expected
        snapshot = json.loads(json.dumps(panel.snapshot()))
        restored = InlineInference(frame, chosen, lambda path: None)
        assert restored.restore(snapshot)
        assert restored.reviewed_path() == expected
        restored.routes.SetSelection(0)
        restored._populate()
        assert restored.controls[0][0][2].GetValue() == '500m'
    finally:
        frame.Destroy()


def test_endpoint_and_unknown_policy_changes_discard_old_models(review):
    panel, _ = review
    assert panel.infer('J1.1', 'J2.1')
    models(panel)
    assert panel.infer('J1.1', 'J2.1')
    assert panel.controls[0][0][2].GetValue() == '100m'
    assert panel.infer('J1.2', 'J2.1')
    assert panel.controls[0][0][2].GetValue() == ''
    models(panel)
    assert panel.infer('J1.2', 'J2.1', True)
    assert panel.controls[0][0][2].GetValue() == ''
    panel.invalidate()
    assert panel.proposal is None
    assert panel.snapshot()['query'] is None
    with pytest.raises(ValueError, match='Infer routes'):
        panel.reviewed_path()


def test_restore_recomputes_routes_and_rejects_changed_current_pin_identity(app):
    frame = wx.Frame(None)
    try:
        panel = InlineInference(frame, inventory(), lambda path: None)
        panel.infer('J1.1', 'J2.1')
        models(panel)
        snapshot = json.loads(json.dumps(panel.snapshot()))
        changed = inventory()
        next(row for row in changed['terminals'] if row['id'] == 'Q1-1')['net'] = 'CTRL1'
        restored = InlineInference(frame, changed, lambda path: None)
        assert restored.restore(snapshot)
        assert restored.controls[0][0][2].GetValue() == ''
        assert restored.controls[0][1][2].GetValue() == '200m'
        # A stale serialized route cannot create connectivity absent from the board.
        disconnected = deepcopy(changed)
        for row in disconnected['terminals']:
            if row['reference'] == 'J2':
                row['net'] = 'ISOLATED'
        unavailable = InlineInference(frame, disconnected, lambda path: None)
        assert not unavailable.restore(snapshot)
        assert unavailable.proposal is None
    finally:
        frame.Destroy()


def test_existing_path_seeds_only_selected_members_and_exact_group_subsets(review):
    panel, _ = review
    panel.infer('J1.1', 'J2.1')
    models(panel)
    panel.controls[0][1][1].SetValue(False)
    panel.controls[1][0][1].SetValue(False)
    panel.controls[0][0][3][0][1].SetValue(False)
    path = panel.reviewed_path()
    path['source_terminals'] = ['J1-1']
    path['sink_terminals'] = ['J2-1']
    panel.invalidate()
    assert panel.infer('J1.1', 'J2.1', existing=path)
    assert panel.reviewed_path() == path
    assert not panel.controls[0][1][1].GetValue()
    assert panel.controls[0][1][2].GetValue() == ''
    saved = panel.snapshot()
    assert panel.restore(saved)
    assert panel.reviewed_path() == path


def test_no_route_and_same_net_fail_inline_without_stale_proposal(review):
    panel, _ = review
    assert panel.infer('J1.1', 'J2.1')
    assert not panel.infer('J1.1', 'missing')
    assert panel.proposal is None
    assert not panel.accept.IsEnabled()
    assert panel.status.GetLabel()
    assert not panel.infer('J1.1', 'J1.2')
    assert 'single-net' in panel.status.GetLabel()


def test_accepted_inference_then_manual_and_parallel_edits_survive_review_and_run(editor, monkeypatch):
    from quick_pi_plugin.series_editor import display_path_command
    editor._infer()
    models(editor.inference)
    editor.inference._use()
    assert editor.inference.proposal is None
    edited = deepcopy(editor._path_data())
    edited['branches'][0]['model'] = '300m'
    editor.manual.ChangeValue(display_path_command(edited, editor.inventory))
    editor._manual_pending = True
    assert editor._apply_manual(None)
    editor.list.SetSelection(0)

    def edit_parallel(dialog):
        def children(window):
            for child in window.GetChildren():
                yield child
                yield from children(child)
        fields = [control for control in children(dialog) if isinstance(control, wx.TextCtrl)]
        assert len(fields) == 1
        assert fields[0].GetValue() == '200m'
        fields[0].SetValue('400m')
        return wx.ID_OK

    # Exercise the existing parallel review handler without displaying its dialog.
    with patch.object(wx.Dialog, 'ShowModal', edit_parallel):
        editor._parallel(None)
    reviewed = editor._reviewed_editor_path()
    assert reviewed['branches'][0]['model'] == '300m'
    assert reviewed['branches'][0]['parallel'][0]['model'] == '400m'
    assert editor.inference.proposal is None
    ended = []
    monkeypatch.setattr(editor.dialog, 'EndModal', ended.append)
    editor._run(None)
    assert ended == [wx.ID_OK]
    assert editor.request['series'][0]['resistance_ohm'] == pytest.approx(.3)
    assert editor.request['series'][0]['parallel'][0]['resistance_ohm'] == pytest.approx(.4)


def test_selected_pcb_endpoints_invalidate_unaccepted_review(editor, monkeypatch):
    editor._infer()
    models(editor.inference)
    monkeypatch.setattr('quick_pi_plugin.series_editor.selected_pad_ids',
                        lambda *args: ['J1-2', 'J2-2'])
    editor._selection(None)
    assert editor._chosen(editor.source) == 'J1.2'
    assert editor._chosen(editor.sink) == 'J2.2'
    assert editor.inference.proposal is None
    assert editor.inference.snapshot()['query'] is None
    with pytest.raises(ValueError):
        editor._reviewed_editor_path()


def test_batch_refresh_clears_selection_and_blocks_hidden_update_or_remove(editor):
    editor._infer()
    models(editor.inference)
    batch = editor.batch_setup
    batch.add()
    assert len(batch.cases) == 1
    batch.selected = 0
    original = deepcopy(batch.cases)
    batch.refresh()
    assert batch.selected == -1
    assert batch.list.GetFirstSelected() == -1
    batch.name.ChangeValue('Unselected edit')
    batch.update()
    assert batch.cases == original
    assert 'Select a batch case' in batch.notice.GetLabel()
    batch.remove()
    assert batch.cases == original
