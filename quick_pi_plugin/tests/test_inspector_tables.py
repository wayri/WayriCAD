"""Pure table contracts and native sorting/map/identity cross-selection."""
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from quick_pi_plugin.inspector_tables import sorted_rows,loss_rows,heating_rows,probe_rows,display
from quick_pi_plugin.tests.test_report import bundle
from quick_pi_plugin.report import inspection_record,METRICS

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None


class TableDataTests(unittest.TestCase):
    def test_numeric_sort_retains_identity_and_keeps_unknown_last(self):
        rows=[{'cells':('ten',10.),'target':{'id':'ten'}},
              {'cells':('two',2.),'target':{'id':'two'}},
              {'cells':('unknown',None),'target':None}]
        self.assertEqual([r['target'] for r in sorted_rows(rows,1)],[{'id':'two'},{'id':'ten'},None])
        self.assertEqual([r['cells'][0] for r in sorted_rows(rows,1,False)],['ten','two','unknown'])
        self.assertEqual(display(None),'Unknown');self.assertEqual(display(float('nan')),'Unknown')
        self.assertEqual(rows[0]['cells'][0],'ten')

    def test_losses_and_probe_have_units_and_exact_cell_targets(self):
        b=bundle();r=b['result'];rows=loss_rows(r)
        layer=next(row for row in rows if row.get('layer') is not None)
        self.assertAlmostEqual(layer['cells'][1],r['total_power_W'])
        self.assertEqual(layer['target']['kind'],'sheet')
        heating=heating_rows(r)
        self.assertEqual(heating[0]['target']['id'],r['analytics']['hotspots_by_heating_density'][0]['id'])
        record=inspection_record(b,'sheet',3,'density');record['source_ids']=['native-track']
        values={row['cells'][0]:row for row in probe_rows(b,record)}
        self.assertEqual(values['Display ID']['cells'][1],'C4')
        self.assertEqual(values['Current density']['cells'][2],'A/mm²')
        self.assertEqual(values['Current density']['metric'],'density')
        self.assertEqual(values['Cell voltage drop']['metric'],'drop')
        self.assertEqual(values['Saved PCB identities']['cells'][1],'native-track')
        self.assertEqual(values['Cell / barrel loss']['cells'][2],'W')
        self.assertIs(values['Current density']['target'],record)
        self.assertIsNone(probe_rows({},None)[0]['target'])

    def test_floating_layer_and_missing_probe_keep_unknown(self):
        b=bundle();r=b['result'];layer=r['analytics']['layers'][0]
        layer.update(peak_location_mm=None,peak_current_density_A_mm2=None)
        r['analytics']['hotspots_by_current_density']=[]
        row=next(row for row in loss_rows(r) if row.get('layer') is not None)
        self.assertIsNone(row['target']);self.assertIsNone(row['cells'][3])
        record={'kind':'object','id':'native-only','layer_name':'F.Cu','location_mm':[1,2],
                'metric':'density','value':None,'unit':'A/mm²','source_ids':['native-only']}
        rows=probe_rows(b,record)
        self.assertIsNone(next(row for row in rows if row['cells'][0]=='Current density')['cells'][1])


@unittest.skipIf(wx is None,'KiCad native wx runtime required')
class NativeInspectorTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_sort_and_cross_select_loss_probe_map_and_exact_native_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic-table.kicad_pcb';board=pcbnew.BOARD()
            net=pcbnew.NETINFO_ITEM(board,'Analytical strip',1);board.Add(net)
            track=pcbnew.PCB_TRACK(board);track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(0),pcbnew.FromMM(.5)))
            track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(10),pcbnew.FromMM(.5)));track.SetWidth(pcbnew.FromMM(1));track.SetLayer(pcbnew.F_Cu);track.SetNetCode(1);board.Add(track)
            pcbnew.SaveBoard(str(path),board)
            with patch.object(QuickPIFrame,'_inspect'):frame=QuickPIFrame(None,str(path))
            try:
                b=bundle();b['geometry']['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                from wayricad_runtime.board_render import extract_board
                b['board_scene']=extract_board(board,['Analytical strip'])
                frame.net.Set(['Analytical strip']);frame.net.SetValue('Analytical strip')
                frame._terminals=[{'id':'A','label':'A.1'},{'id':'B','label':'B.1'}]
                for control,index in ((frame.source,0),(frame.sink,1)):
                    control.Set(['A.1','B.1']);control.SetSelection(index)
                frame._accept_result(b,b['request'],'solve');frame.Show();self.app.Yield()
                frame.inspector_views.SetSelection(1)
                self.assertGreater(frame.loss_table.GetItemCount(),0)
                table=frame.heating_table
                table._column_clicked(SimpleNamespace(GetColumn=lambda:3))
                self.assertEqual(table.sort_column,3)
                table._column_clicked(SimpleNamespace(GetColumn=lambda:3))
                self.assertFalse(table.ascending)
                target=table.rows[0]['target']
                table._selected(SimpleNamespace(GetIndex=lambda:0));self.app.Yield()
                self.assertEqual(frame._inspection['id'],target['id'])
                self.assertEqual(frame._inspection['metric'],'loss')
                self.assertEqual(frame._inspection['source_ids'],[track.m_Uuid.AsString()])
                self.assertTrue(frame.inspector_select.IsEnabled())
                density=next(row for row in frame.probe_table.rows if row['cells'][0]=='Current density')
                frame.probe_table._selected(SimpleNamespace(GetIndex=lambda:frame.probe_table.rows.index(density)))
                self.app.Yield()
                self.assertEqual(list(METRICS)[frame.metric.GetSelection()],'density')
                self.assertEqual(frame._inspection['id'],target['id'])
                with patch.object(frame,'_select_ids') as select:
                    frame._select_inspected();select.assert_called_once_with([track.m_Uuid.AsString()])
                frame._choose_inspection(inspection_record(b,'sheet',5,'drop'),focus=True);self.app.Yield()
                identity=next(row for row in frame.probe_table.rows if row['cells'][0]=='Display ID')
                self.assertEqual(identity['cells'][1],'C6')
                self.assertEqual(identity['target']['id'],5)
                frame.probe_table._column_clicked(SimpleNamespace(GetColumn=lambda:0))
                self.assertEqual(frame.probe_table.rows[0]['cells'][0],'Adiabatic pulse temperature')
                for width in (960,1320):
                    frame.SetSize((width,800));self.app.Yield()
                    self.assertGreater(frame.probe_table.GetClientSize().width,50)
                self.assertGreaterEqual(frame.probe_table.GetColumnWidth(1),90)
                self.assertGreaterEqual(frame.probe_table.GetColumnWidth(2),60)
                self.assertLessEqual(sum(frame.probe_table.GetColumnWidth(i) for i in range(3)),max(290,frame.probe_table.GetClientSize().width))
                frame.probe_table.SetColumnWidth(0,190)
                frame.probe_table._column_resized(SimpleNamespace(Skip=lambda:None))
                frame.SetSize((1180,800));self.app.Yield()
                self.assertEqual(frame.probe_table.GetColumnWidth(0),190)
                capture=os.environ.get('WAYRICAD_PI_TABLE_CAPTURE')
                if capture:
                    frame.SetSize((1320,800));frame.splitter.SetSashPosition(max(200,frame.splitter.GetClientSize().width-360));self.app.Yield()
                    frame.probe_table._manual_columns=False
                    frame.probe_table._resized(SimpleNamespace(Skip=lambda:None))
                    for page,suffix,subpage in ((1,'-losses',0),(1,'-heating',1),(2,'',0)):
                        frame.losses_book.SetSelection(subpage)
                        frame.inspector_views.SetSelection(page);frame.Refresh();frame.Update();self.app.Yield()
                        frame.views[2][1].draw();frame.Refresh();frame.Update();self.app.Yield()
                        w,h=frame.main_panel.GetClientSize();bitmap=wx.Bitmap(w,h);dc=wx.MemoryDC(bitmap)
                        self.assertTrue(dc.Blit(0,0,w,h,wx.ClientDC(frame.main_panel),0,0));dc.SelectObject(wx.NullBitmap)
                        target=Path(capture);target=target.with_name(target.stem+suffix+target.suffix)
                        self.assertTrue(bitmap.SaveFile(str(target),wx.BITMAP_TYPE_PNG))
                path.write_bytes(path.read_bytes()+b'\n');frame._draw();self.app.Yield()
                self.assertEqual(frame.loss_table.GetItemCount(),0)
                self.assertEqual(frame.heating_table.GetItemCount(),0)
                self.assertIsNone(frame.probe_table.rows[0]['target'])
            finally:
                frame._end();wx.CallLater(100,self.app.ExitMainLoop);self.app.MainLoop()


if __name__=='__main__':unittest.main()
