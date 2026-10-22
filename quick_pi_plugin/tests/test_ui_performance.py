"""Native redraw reuse and exact selection scope on a disposable board."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None

_app=None


@unittest.skipIf(wx is None,'KiCad native wx runtime required')
class ResponsiveViewTests(unittest.TestCase):
    def test_unchanged_redraw_reuses_artists_search_preserves_solution_and_scope_is_exact(self):
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board,portrait_result
        from quick_pi_plugin.report import draw_view
        global _app
        _app=wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'display-test.kicad_pcb';portrait_board(path)
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,str(path))
                try:
                    frame.net.Set(['5V_DEMO','5V_DEMO_AUX','GND']);frame.net.SetValue('5V_DEMO')
                    frame.inventory={'nets':['5V_DEMO','5V_DEMO_AUX','GND']}
                    data=portrait_result();data['geometry']['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                    from wayricad_runtime.board_render import extract_board
                    data['board_scene']=extract_board(pcbnew.LoadBoard(str(path)),['5V_DEMO'])
                    frame._accept_result(data,data['request'],'solve')
                    figure=frame.views[2][0];axes=figure.axes[0]
                    axes.set_xlim(20,40);axes.set_ylim(60,20)
                    with patch('quick_pi_plugin.ui.draw_view',wraps=draw_view) as render:
                        frame._draw(preserve=True)
                        render.assert_not_called()
                        self.assertIs(figure.axes[0],axes)
                        self.assertEqual(axes.get_xlim(),(20,40))
                        frame.metric.SetSelection((frame.metric.GetSelection()+1)%frame.metric.GetCount());frame._draw(preserve=True)
                        render.assert_called_once()
                    # The legend is shared across pages, while artists are cached per page.
                    frame.book.SetSelection(0);frame._draw()
                    self.assertIsNone(frame.color_legend.scale)
                    frame.book.SetSelection(2)
                    with patch('quick_pi_plugin.ui.draw_view',wraps=draw_view) as render:
                        frame._draw();render.assert_not_called()
                    self.assertIsNotNone(frame.color_legend.scale)
                    saved=path.read_bytes();path.write_bytes(saved+b'\n');frame._draw()
                    self.assertIsNone(getattr(figure,'_wayricad_render_key',None))
                    path.write_bytes(saved)
                    with patch('quick_pi_plugin.ui.draw_view',wraps=draw_view) as render:
                        frame._draw();render.assert_called_once()
                    frame.net_search.ChangeValue('G*')
                    with patch.object(frame,'_net_changed') as changed:
                        frame._filter_nets();changed.assert_not_called()
                    self.assertIs(frame.bundle['result'],data['result'])
                    self.assertEqual(frame.net.GetValue(),'5V_DEMO')
                    import copy
                    incoming=copy.deepcopy(data);incoming.pop('board_scene',None)
                    frame._board_scene={'net_scope':['OTHER'],'primitives':[]}
                    frame._board_scene_hash=incoming['geometry']['source_sha256']
                    with patch('quick_pi_plugin.ui.wx.CallAfter') as schedule,patch.object(pcbnew,'LoadBoard') as load:
                        frame._accept_result(incoming,incoming['request'],'solve')
                        schedule.assert_called_once_with(frame._load_result_scene,incoming,
                                                         incoming['geometry']['source_sha256'],['5V_DEMO'])
                        load.assert_not_called()
                        self.assertEqual(frame._board_scene,{})
                    frame._board_scene={'primitives':[
                        dict(uuid='selected',net='5V_DEMO',role='track'),
                        dict(uuid='duplicate-layer',net='5V_DEMO',role='via'),
                        dict(uuid='duplicate-layer',net='5V_DEMO',role='via'),
                        dict(uuid='wrong',net='5V_DEMO_AUX',role='track'),
                        dict(uuid='ground',net='GND',role='pad')]}
                    with patch.object(frame,'_select_ids') as select:
                        frame._select_net_scope()
                        select.assert_called_once_with(['duplicate-layer','selected'],additive=False)
                finally:
                    frame._end();_app.Yield()


if __name__=='__main__':unittest.main()
