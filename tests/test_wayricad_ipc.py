"""Real kicad-python value contracts with a fake transport, never live-board proof.

Run with kicad-python 0.8 installed (or PYTHONPATH=.build-tools in this checkout).
"""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from wayricad_runtime.ipc import Board, IPCPolySet, UnsupportedCapability, module
from wayricad_runtime import launcher

try:
    from kipy import board_types as types
    from kipy.geometry import Vector2, Angle, Box2, PolygonWithHoles, PolyLineNode
    from kipy.kicad import KiCadVersion
    from kipy.proto.board.board_types_pb2 import BoardLayer, PadType, ZoneType
except ImportError:
    types=None


@unittest.skipIf(types is None,'Install kicad-python 0.8 to check actual SDK contracts')
class SDKContractTests(unittest.TestCase):
    def setUp(self):
        self.raw=Mock()
        self.raw.get_nets.return_value=[types.Net(name='GND')]
        self.raw.get_enabled_layers.return_value=[BoardLayer.BL_F_Cu,BoardLayer.BL_B_Cu]
        self.raw.get_selection.return_value=[]
        self.raw.get_shapes.return_value=[]
        self.client=Mock()
        self.client.get_version.return_value=KiCadVersion(10,0,0,'10.0.0')
        self.client.get_board.return_value=self.raw
        self.api=module(self.client)
        self.board=self.api.GetBoard()

    def rect(self,x,y,u,v):
        shape=types.BoardRectangle()
        shape.layer=BoardLayer.BL_Edge_Cuts
        shape.top_left=Vector2.from_xy(x,y);shape.bottom_right=Vector2.from_xy(u,v)
        return shape

    def test_track_and_via_values_use_net_names_and_enabled_span(self):
        track=self.api.PCB_TRACK(self.board)
        track.SetStart(self.api.VECTOR2I(100,200));track.SetEnd(self.api.VECTOR2I(400,600))
        track.SetWidth(100);track.SetLayer(self.api.F_Cu)
        track.SetNet(self.board.FindNet('GND'))
        self.assertEqual(track.GetLength(),500)
        self.assertEqual(track.raw.proto.net.name,'GND')
        via=self.api.PCB_VIA(self.board)
        via.SetPosition(self.api.VECTOR2I(400,600));via.SetWidth(600000);via.SetDrill(300000)
        via.SetLayerPair(self.api.F_Cu,self.api.B_Cu)
        self.assertEqual(via.GetDrillValue(),300000)
        self.assertEqual(via.GetWidth(),600000)
        self.assertEqual(via.GetLayerSet().CuStack(),[self.api.F_Cu,self.api.B_Cu])
        self.assertEqual(via.GetStart().x,via.GetEnd().x)

    def test_footprint_fields_and_library_id_use_real_sdk_properties(self):
        fp=types.FootprintInstance();fp.id.value='fp'
        fp.definition.id.library='Device';fp.definition.id.name='R_0603'
        fp.reference_field.text.value='R1';fp.value_field.text.value='1k'
        fp.orientation=Angle.from_degrees(90)
        fp.attributes.exclude_from_bill_of_materials=True;fp.attributes.do_not_populate=True
        wrapped=self.board.wrap(fp)
        self.assertEqual(str(wrapped.GetFPID()),'Device:R_0603')
        self.assertEqual(wrapped.GetFPID().GetLibNickname(),'Device')
        self.assertEqual(wrapped.GetOrientation().AsDegrees(),90)
        self.assertEqual(wrapped.GetAttributes(),self.api.FP_EXCLUDE_FROM_BOM|self.api.FP_DNP)
        fields=wrapped.GetFields()
        self.assertEqual(len(fields),4)
        self.assertIn('R1',[f.GetText() for f in fields])
        self.raw.update_items.side_effect=lambda items:items
        wrapped.SetValue('2k')
        self.assertEqual(fp.value_field.text.value,'2k')
        self.raw.update_items.return_value=[];self.raw.update_items.side_effect=None
        with self.assertRaisesRegex(RuntimeError,'acknowledge'):wrapped.SetValue('3k')

    def test_smd_pad_is_distinguished_and_uses_native_angle_size(self):
        pad=types.Pad();pad.id.value='pad';pad.number='1'
        pad.pad_type=PadType.PT_SMD
        pad.padstack.layers=[self.api.F_Cu]
        pad.padstack.angle=Angle.from_degrees(45)
        pad.padstack.copper_layers[0].size=Vector2.from_xy(100,200)
        wrapped=self.board.wrap(pad)
        self.assertEqual(wrapped.GetAttribute(),self.api.PAD_ATTRIB_SMD)
        self.assertEqual(wrapped.GetOrientationDegrees(),45)
        self.assertEqual(wrapped.GetSize().y,200)
        pad.pad_type=PadType.PT_PTH
        self.assertNotEqual(wrapped.GetAttribute(),self.api.PAD_ATTRIB_SMD)

    def test_rule_areas_do_not_invent_via_prohibitions(self):
        zone=types.Zone();zone.id.value='zone';zone.type=ZoneType.ZT_RULE_AREA
        wrapped=self.board.wrap(zone)
        self.assertFalse(wrapped.GetDoNotAllowVias())
        zone.proto.rule_area_settings.keepout_vias=True
        self.assertTrue(wrapped.GetDoNotAllowVias())
        self.assertFalse(wrapped.GetDoNotAllowTracks())

    def test_outline_keeps_cutouts_and_disjoint_islands(self):
        self.raw.get_shapes.return_value=[self.rect(0,0,100,100),self.rect(20,20,30,30),self.rect(200,0,300,100)]
        poly=self.board.wayricad_outline()
        self.assertEqual(poly.OutlineCount(),2)
        self.assertEqual(sum(poly.HoleCount(i) for i in range(2)),1)

    def test_outline_joins_segments_without_guessing_over_gaps(self):
        shapes=[]
        for a,b in [((0,0),(100,0)),((100,100),(100,0)),((0,100),(100,100)),((0,0),(0,100))]:
            shape=types.BoardSegment();shape.layer=BoardLayer.BL_Edge_Cuts
            shape.start=Vector2.from_xy(*a);shape.end=Vector2.from_xy(*b);shapes.append(shape)
        self.raw.get_shapes.return_value=shapes
        self.assertEqual(self.board.wayricad_outline().OutlineCount(),1)
        self.raw.get_shapes.return_value=shapes[:-1]
        with self.assertRaisesRegex(UnsupportedCapability,'open'):self.board.wayricad_outline()
        self.raw.get_shapes.return_value=[self.rect(0,0,100,100),self.rect(50,50,150,150)]
        with self.assertRaisesRegex(UnsupportedCapability,'intersect'):self.board.wayricad_outline()
        curve=types.BoardCircle();curve.layer=BoardLayer.BL_Edge_Cuts
        self.raw.get_shapes.return_value=[curve]
        with self.assertRaisesRegex(UnsupportedCapability,'Curves'):self.board.wayricad_outline()

    def test_missing_bounding_box_and_old_host_fail_explicitly(self):
        self.raw.get_item_bounding_box.return_value=None
        with self.assertRaises(UnsupportedCapability):self.board.wrap(types.Pad()).GetBoundingBox()
        self.client.get_version.return_value=KiCadVersion(9,0,0,'9.0.0')
        with self.assertRaisesRegex(UnsupportedCapability,'10 or later'):module(self.client)


class LauncherTests(unittest.TestCase):
    def test_launches_packaged_relative_import_and_local_event_loop(self):
        app=SimpleNamespace(MainLoop=Mock())
        wx=SimpleNamespace(App=SimpleNamespace(Get=lambda:app),GetTopLevelWindows=lambda:[object()])
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            root.joinpath('__init__.py').write_text('',encoding='utf-8')
            root.joinpath('action.py').write_text('ran=False\nclass Tool:\n    def Run(self):\n        global ran\n        ran=True\n',encoding='utf-8')
            root.joinpath('wayricad-tool.json').write_text(json.dumps({'tool':'test_plugin','module':'action','class':'Tool','name':'WayriCAD Test'}),encoding='utf-8')
            with patch.dict(sys.modules,{'wx':wx}),patch('wayricad_runtime.ipc.module',return_value=SimpleNamespace(_wayricad_ipc=True)):
                self.assertEqual(launcher.main(root),0)
                self.assertTrue(sys.modules['wayricad_active_plugin.action'].ran)
                app.MainLoop.assert_called_once()

    def test_bad_metadata_returns_failure_and_local_error(self):
        wx=SimpleNamespace(App=SimpleNamespace(Get=lambda:object()),MessageBox=Mock(),OK=1,ICON_ERROR=2)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'wayricad-tool.json').write_text('{}',encoding='utf-8')
            with patch.dict('sys.modules',{'wx':wx}),patch('sys.stderr'):
                self.assertEqual(launcher.main(directory),1)
            self.assertIn('invalid launch metadata',wx.MessageBox.call_args.args[0])


if __name__=='__main__':unittest.main()
