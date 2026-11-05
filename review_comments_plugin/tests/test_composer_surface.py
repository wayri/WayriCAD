"""Native editor surface keeps long Markdown drafts usable in both palettes."""
import pytest

wx = pytest.importorskip('wx')

from review_comments_plugin.tests.test_conversation_ui import app, pane


def test_padded_scrollable_editor_retains_text_selection_and_local_preview(pane):
    composer = pane.composer
    editor = composer.editor
    assert composer.book.GetPage(0) is composer.entry
    assert editor.GetParent() is composer.editor_surface
    assert editor.GetWindowStyleFlag() & wx.VSCROLL
    assert not editor.GetWindowStyleFlag() & wx.TE_NO_VSCROLL
    text = 'Review R1\n' * 300
    editor.SetValue(text)
    editor.SetSelection(0, 6)
    pane.toggle_theme()
    assert editor.GetValue() == text
    assert editor.GetSelection() == (0, 6)
    assert editor.GetBackgroundColour() == wx.Colour('#202733')
    composer.toggle_preview()
    assert composer.book.GetSelection() == 1
    composer.toggle_preview()
    assert editor.GetValue() == text
    editor.SetValue('x' * 16000)
    editor.SetInsertionPointEnd()
    composer.insert_text('y')
    assert editor.GetValue() == 'x' * 16000
    assert '16000' in pane.status.GetLabel()


def test_editor_focus_border_uses_current_palette_without_touching_draft(pane):
    composer = pane.composer
    composer.editor.SetValue('Keep this draft')
    event = wx.FocusEvent(wx.wxEVT_SET_FOCUS, composer.editor.GetId())
    composer.editor_focus(event)
    assert composer._entry_focused
    pane.toggle_theme()
    assert composer.editor.GetValue() == 'Keep this draft'
    assert composer.entry.GetBackgroundColour() == wx.Colour('#202733')
    composer.editor_focus(wx.FocusEvent(wx.wxEVT_KILL_FOCUS, composer.editor.GetId()))
    assert not composer._entry_focused


def test_compact_attachment_controls_explain_available_actions(pane):
    composer = pane.composer
    assert composer.context_button.GetLabel() == 'Attach location…'
    location_tip = composer.context_button.GetToolTip().GetTip()
    for target in ('component', 'BOM cell', 'Gerber', 'point'):
        assert target in location_tip
    assert not hasattr(composer, 'image_button')
    assert 'Ctrl+V' in composer.editor.GetToolTipText()
    assert 'More → Attach image' in composer.editor.GetToolTipText()
    assert not hasattr(composer, 'paste_button')
    assert composer.editor.GetDropTarget() is not None


def test_location_action_does_not_stretch_across_composer(pane, app):
    pane.SetSize((1440, 900))
    pane.Show()
    pane.Layout()
    app.Yield()
    button = pane.composer.context_button
    assert button.GetSize().width <= button.GetBestSize().width + 2
    assert button.GetSize().width < pane.composer.GetSize().width / 2
