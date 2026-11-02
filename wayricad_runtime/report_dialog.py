"""Shared native report format choices; wx is loaded only for the dialog."""
from pathlib import Path


def choose_report_path(parent, directory, stem, title='Export report'):
    import wx
    with wx.FileDialog(parent, title, defaultDir=str(directory), defaultFile=stem,
                       wildcard='HTML report (*.html)|*.html|PDF report (*.pdf)|*.pdf',
                       style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        raw = Path(dialog.GetPath())
        if raw.suffix.lower() not in ('', '.html', '.htm', '.pdf'):
            wx.MessageBox('Choose an HTML or PDF report file.', title, wx.OK | wx.ICON_ERROR, parent)
            return None
        path = raw.with_suffix('.pdf' if dialog.GetFilterIndex() == 1 else '.html')
        html=path.with_suffix('.html')
        targets=[path,html,html.with_suffix('.json'),html.with_name(html.stem+'.pocket-kivi.json')]
        replacements=list(dict.fromkeys(target for target in targets if target!=raw and target.exists()))
        if replacements:
            if wx.MessageBox('Replace existing companion report files?\n'+'\n'.join(map(str,replacements)), title,
                             wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent) != wx.YES:
                return None
        return path


def saved_report_message(result):
    formats = 'PDF, HTML' if result.get('pdf') else 'HTML'
    return ('Saved '+formats+', complete numerical JSON'+
            (' and Pocket KiVi JSON' if result.get('pocket_kivi_json') else '')+
            ': '+str(result.get('pdf') or result['html']))
