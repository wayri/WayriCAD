"""Native selected-row paint and All tools filtering, without live app input."""
import pytest
wx=pytest.importorskip('wx')

from wayricad_runtime.tool_picker import create_tool_list, text_colours


@pytest.mark.parametrize('dark',[False,True])
def test_native_selected_row_draws_readable_text_and_retains_full_name(dark):
    app=wx.GetApp() or wx.App(False)
    frame=wx.Frame(None);panel=wx.Panel(frame)
    panel.SetBackgroundColour('#202124' if dark else '#ffffff')
    choices=create_tool_list(panel)
    try:
        label='WayriCAD Review — a long complete name'
        choices.Set([label]);choices.SetSelection(0)
        assert choices.GetStringSelection()==label and choices.GetToolTipText()==label
        bitmap=wx.Bitmap(300,40);dc=wx.MemoryDC(bitmap)
        rect=wx.Rect(0,0,300,40)
        choices.OnDrawBackground(dc,rect,0);choices.OnDrawItem(dc,rect,0)
        assert dc.GetTextForeground()==wx.Colour(text_colours(True,dark)[0])
        assert dc.GetBrush().GetColour()==wx.Colour(text_colours(True,dark)[1])
        dc.SelectObject(wx.NullBitmap)
        choices.Set([])
        assert choices.GetStringSelection()==''
    finally:frame.Destroy();app.Yield()


def test_all_tools_search_finds_new_review_install_without_legacy_registration(tmp_path,monkeypatch):
    import json
    from wayricad_runtime import legacy_menu
    app=wx.GetApp() or wx.App(False)
    root=tmp_path/'10.0/3rdparty/plugins/com_github_wayri_wayricad_bom-studio'
    root.mkdir(parents=True)
    review=tmp_path/'10.0/plugins/com.github.wayri.wayricad.review-comments'
    review.mkdir(parents=True)
    (review/'plugin.json').write_text(json.dumps(dict(identifier=review.name,actions=[dict(
        name='WayriCAD Review',scopes=['pcb'],entrypoint='ipc_entrypoint.py')])) )
    (review/'desktop_entrypoint.py').write_text('raise RuntimeError("Not executed by search")')
    monkeypatch.setattr(legacy_menu,'MENU_ACTIONS',{})
    original=wx.Dialog
    def offscreen(*args,**kwargs):
        dialog=original(*args,**kwargs);dialog.Move((-18000,-18000));return dialog
    monkeypatch.setattr(wx,'Dialog',offscreen)
    outcome={}
    def accept():
        dialog=next(w for w in wx.GetTopLevelWindows() if w.GetTitle()=='WayriCAD — All tools')
        try:
            panel=dialog.GetChildren()[0]
            search=next(c for c in panel.GetChildren() if isinstance(c,wx.SearchCtrl))
            choices=next(c for c in panel.GetChildren() if hasattr(c,'names'))
            button=dialog.FindWindow(wx.ID_OK)
            search.SetValue('unmatched tool');assert not button.IsEnabled()
            search.SetValue('wayricad review');assert choices.GetStringSelection()=='WayriCAD Review'
            assert button.IsEnabled()
            button.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK))
            outcome['passed']=True
        except Exception as error:
            outcome['error']=error;dialog.EndModal(wx.ID_CANCEL)
    wx.CallLater(30,accept)
    chosen=legacy_menu._choose_tool(root)
    if 'error' in outcome:raise outcome['error']
    assert outcome['passed'] and chosen.name=='WayriCAD Review' and chosen.location==review
