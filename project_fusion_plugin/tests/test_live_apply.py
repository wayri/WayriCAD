"""Protocol-unit tests. These do not claim a native-window IPC/undo test."""
import copy,importlib,json,sys,unittest,uuid
from unittest import mock
from pathlib import Path
from types import ModuleType,SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];PACKAGE='_fusion_live_test'
pkg=ModuleType(PACKAGE);pkg.__path__=[str(ROOT)];sys.modules[PACKAGE]=pkg
live=importlib.import_module(PACKAGE+'.live_apply');sx=importlib.import_module(PACKAGE+'.sexpr')

def desc(name,message=None,enum=None):return NS(name=name,message_type=NS(GetOptions=lambda:NS(map_entry=False)) if message else None,enum_type=enum,is_repeated=False)
class KIID:
    DESCRIPTOR=NS(name='KIID')
    def __init__(self,value):self.value=value
    def ListFields(self):return []
class Net:
    DESCRIPTOR=NS(name='Net',fields_by_name={'code':True})
    def __init__(self,name,code=77):self.name=name;self.code=code
    def ClearField(self,key):setattr(self,key,0)
    def ListFields(self):return []
class Proto:
    DESCRIPTOR=NS(name='Item')
    def __init__(self,uid,ref='R1',name='',x=1000000,y=2000000,angle=0,layer=1):
        self.id=KIID(uid);self.ref=ref;self.net=Net(name);self.x=x;self.y=y;self.angle=angle;self.layer=layer
    def ListFields(self):return [(desc('id',message=True),self.id),(desc('net',message=True),self.net),(desc('layer',enum=NS(name='BoardLayer',values_by_number={1:NS(name='BL_F_Cu'),2:NS(name='BL_B_Cu'),3:NS(name='BL_In1_Cu')})),self.layer)]
    def SerializeToString(self,deterministic=True):return json.dumps(vars(self),sort_keys=True,default=lambda x:vars(x)).encode()
class Position:
    def __init__(self,x,y):self.x=x;self.y=y
    @classmethod
    def from_xy(cls,x,y):return cls(x,y)
class Angle:
    def __init__(self,value):self.degrees=value
    @classmethod
    def from_degrees(cls,value):return cls(value)
class Item:
    def __init__(self,proto):self.proto=copy.deepcopy(proto)
    @property
    def id(self):return self.proto.id
class Footprint(Item):
    locked=False
    @property
    def reference_field(self):return NS(text=NS(value=self.proto.ref))
    @property
    def position(self):return Position(self.proto.x,self.proto.y)
    @position.setter
    def position(self,p):self.proto.x=p.x;self.proto.y=p.y
    @property
    def orientation(self):return Angle(self.proto.angle)
    @orientation.setter
    def orientation(self,a):self.proto.angle=a.degrees
class Board:
    def __init__(self):
        self.document={'board_filename':'C:/Projects/Example/board.kicad_pcb'}
        self.items=[Footprint(Proto('11111111-1111-4111-8111-111111111111'))];self.note='unsaved-user-work';self.extra=[];self.calls=[];self.undo=[];self.failure=None;self.begin_hook=None
    def get_as_string(self):
        root=['kicad_pcb',['version','20250114'],['gr_text',sx.q(self.note),['at','0','0'],['uuid',sx.q('22222222-2222-4222-8222-222222222222')]]]
        for i in self.items:
            root.append(['footprint',sx.q('Device:R'),['layer',sx.q('F.Cu' if i.proto.layer==1 else 'B.Cu')],['uuid',sx.q(i.id.value)],['at',str(i.proto.x/1e6),str(i.proto.y/1e6),str(i.proto.angle)],['property',sx.q('Reference'),sx.q(i.proto.ref)],['pad',sx.q('1'),'smd','rect',['net',sx.q(i.proto.net.name)]]])
        return sx.dumps(root+copy.deepcopy(self.extra))
    def get_footprints(self):return copy.deepcopy(self.items)
    def get_nets(self):return [Net('GND')]
    def get_enabled_layers(self):return [1,2]
    def get_items_by_id(self,ids):return [copy.deepcopy(i) for i in self.items if i.id.value in {u.value for u in ids}]
    def begin_commit(self):
        self.calls.append('begin')
        if self.begin_hook:self.begin_hook(self)
        self.before=copy.deepcopy((self.items,self.note,self.extra));return object()
    def drop_commit(self,tx):
        self.calls.append('drop')
        if self.failure=='rollback':raise RuntimeError('native drop failed')
        self.items,self.note,self.extra=copy.deepcopy(self.before)
    def push_commit(self,tx,title):self.calls.append('push');self.undo.append((title,self.before))
    def update_items(self,items):
        self.calls.append('update')
        ids={i.id.value:i for i in items};self.items=[copy.deepcopy(ids.get(i.id.value,i)) for i in self.items]
        if self.failure=='unrelated':self.note='clobbered'
        if self.failure in ('partial','rollback'):return []
        if self.failure=='clamp':self.items[0].proto.x+=1
        return self.get_items_by_id([i.id for i in items])
    def create_items(self,items):self.calls.append('create');self.items+=copy.deepcopy(items);return copy.deepcopy(items)

class LiveApplyTests(unittest.TestCase):
    def preview(self,board):
        candidate=sx.loads(board.get_as_string());sx.child(sx.child(candidate,'footprint'),'at')[1]='3.0'
        return live.preview_placement(board,candidate)
    def review(self,plan):return dict(plan_sha256=plan.plan_sha256,source_board_sha256=plan.snapshot['board_sha256'],rules_sha256=plan.snapshot['rules_sha256'],native_candidate_nonregression_verified=True)
    def test_supported_move_preserves_unsaved_note_and_groups_native_undo(self):
        board=Board();plan=self.preview(board);self.assertNotIn('update',board.calls)
        result=live.apply_plan(board,plan,native_review=self.review(plan))
        self.assertTrue(result['applied']);self.assertFalse(result['files_written']);self.assertEqual(board.note,'unsaved-user-work');self.assertEqual(board.items[0].proto.x,3000000)
        self.assertEqual(board.calls,['begin','update','push']);self.assertEqual(len(board.undo),1)
        board.items,board.note,board.extra=copy.deepcopy(board.undo[-1][1]);self.assertEqual(board.items[0].proto.x,1000000)
    def test_stale_unsaved_edit_stops_before_transaction(self):
        board=Board();plan=self.preview(board);board.note='new unsaved edit'
        with self.assertRaises(live.StaleLivePlan):live.apply_plan(board,plan,native_review=self.review(plan))
        self.assertEqual(board.calls,[]);self.assertEqual(board.note,'new unsaved edit')
    def test_edit_at_begin_stops_and_retains_latest_user_state(self):
        board=Board();plan=self.preview(board);board.begin_hook=lambda b:setattr(b,'note','edit before transaction')
        with self.assertRaises(live.StaleLivePlan):live.apply_plan(board,plan,native_review=self.review(plan))
        self.assertEqual(board.calls,['begin','drop']);self.assertEqual(board.note,'edit before transaction')
    def test_partial_clamped_and_unrelated_writes_roll_back(self):
        for failure in ('partial','clamp','unrelated'):
            with self.subTest(failure=failure):
                board=Board();plan=self.preview(board);before=board.get_as_string();board.failure=failure
                with self.assertRaises(live.MergeError):live.apply_plan(board,plan,native_review=self.review(plan))
                self.assertEqual(board.get_as_string(),before);self.assertEqual(board.calls[-1],'drop');self.assertNotIn('push',board.calls)
    def test_rollback_failure_is_explicit(self):
        board=Board();plan=self.preview(board);board.failure='rollback'
        with self.assertRaises(live.LiveRollbackError):live.apply_plan(board,plan,native_review=self.review(plan))
    def test_native_review_required_and_hash_bound(self):
        board=Board();plan=self.preview(board)
        with self.assertRaises(live.StaleLivePlan):live.apply_plan(board,plan,native_review={})
        review=self.review(plan);review['native_candidate_nonregression_verified']=False
        with self.assertRaises(live.UnsupportedLiveApply):live.apply_plan(board,plan,native_review=review)
        self.assertEqual(board.calls,[])
    def test_plan_payload_mutation_rejected(self):
        board=Board();plan=self.preview(board);review=self.review(plan);plan.updates[0].proto.x+=1
        with self.assertRaises(live.StaleLivePlan):live.apply_plan(board,plan,native_review=review)
        self.assertEqual(board.calls,[])
    def test_originating_document_switch_rejected(self):
        board=Board();plan=self.preview(board);board.document={'board_filename':'C:/Projects/Other/board.kicad_pcb'}
        with self.assertRaises(live.StaleLivePlan):live.apply_plan(board,plan,native_review=self.review(plan))
    def test_flip_routed_net_and_addition_are_not_placement(self):
        for change in ('flip','route','add'):
            board=Board()
            if change=='route':board.items[0].proto.net.name='GND';board.extra=[['segment',['net',sx.q('GND')],['uuid',sx.q('33333333-3333-4333-8333-333333333333')]]]
            candidate=sx.loads(board.get_as_string());fp=sx.child(candidate,'footprint');sx.child(fp,'at')[1]='3.0'
            if change=='flip':sx.child(fp,'layer')[1]=sx.q('B.Cu')
            if change=='add':candidate.append(['footprint',sx.q('x'),['uuid',sx.q(str(uuid.uuid4()))],['at','0','0']])
            with self.assertRaises(live.UnsupportedLiveApply):live.preview_placement(board,candidate)
    def test_import_uuids_deterministic_net_code_cleared_and_existing_nets_only(self):
        board=Board();item=Footprint(Proto('44444444-4444-4444-8444-444444444444','R2','GND'))
        first=live.preview_items(board,[item],'instance-a');second=live.preview_items(board,[item],'instance-a');third=live.preview_items(board,[item],'instance-b')
        self.assertEqual(first.uuid_map,second.uuid_map);self.assertNotEqual(first.uuid_map,third.uuid_map);self.assertEqual(first.additions[0].proto.net.code,0);self.assertEqual(item.proto.net.code,77)
        live.apply_plan(board,first,native_review=self.review(first));self.assertEqual(len(board.items),2)
        with self.assertRaises(live.StaleLivePlan):live.preview_items(board,[item],'instance-a')
        item.proto.net.name='NEW'
        with self.assertRaises(live.UnsupportedLiveApply):live.preview_items(Board(),[item],'new')
    def test_connect_binds_exact_document_not_first_and_never_enables_ipc(self):
        requested=Path('C:/Projects/Example/board.kicad_pcb')
        docs=[NS(board_filename='C:/Projects/Other/board.kicad_pcb',project=NS(path='C:/Projects/Other')),
              NS(board_filename=str(requested),project=NS(path='C:/Projects/Example'))]
        client=NS(_client=object(),get_version=lambda:NS(major=10),get_open_documents=lambda kind:docs)
        selected=[]
        def factory(connection,doc):
            selected.append(doc);board=Board();board.document=doc;return board
        api=ModuleType('kipy');api.KiCad=mock.Mock(side_effect=AssertionError('Do not connect without originating endpoint'))
        board_module=ModuleType('kipy.board');board_module.Board=factory
        types=ModuleType('kipy.proto.common.types');types.DocumentType=NS(DOCTYPE_PCB=1)
        with mock.patch.dict(sys.modules,{'kipy':api,'kipy.board':board_module,'kipy.proto.common.types':types}):
            live.connect_originating_board(requested,client=client)
            self.assertEqual(selected,[docs[1]])
            with mock.patch.dict(live.os.environ,{'KICAD_API_SOCKET':'','KICAD_API_TOKEN':''}):
                with self.assertRaises(live.UnsupportedLiveApply):live.connect_originating_board(requested)
            api.KiCad.assert_not_called()
            docs.append(copy.deepcopy(docs[1]))
            with self.assertRaises(live.UnsupportedLiveApply):live.connect_originating_board(requested,client=client)

    def test_disabled_layer_schematic_and_missing_ipc_fail_closed(self):
        board=Board();item=Footprint(Proto('44444444-4444-4444-8444-444444444444','R2','GND',layer=3))
        with self.assertRaises(live.UnsupportedLiveApply):live.preview_items(board,[item],'a')
        with self.assertRaises(live.UnsupportedLiveApply):live.preview_items(board,[item],'a',schematic_required=True)
        self.assertFalse(live.capabilities()['pcb_live_available']);self.assertFalse(live.capabilities(board)['schematic_live_available'])
        with self.assertRaises(live.UnsupportedLiveApply):live.capture_snapshot(NS(document={}))

try:
    from kipy.board_types import FootprintInstance as SDKFootprint, Pad as SDKPad, Net as SDKNet
    from kipy.geometry import Vector2 as SDKVector, Angle as SDKAngle
    from kipy.proto.board.board_types_pb2 import BL_F_Cu, BL_B_Cu, BL_In1_Cu
    SDK_AVAILABLE=True
except ImportError:SDK_AVAILABLE=False

@unittest.skipUnless(SDK_AVAILABLE,'Official kicad-python not installed in this test interpreter')
class OfficialSDKDataTests(unittest.TestCase):
    """Actual installed SDK protobuf roundtrip; not a connected editor test."""
    def sdk_item(self):
        fp=SDKFootprint();fp.id.value='55555555-5555-4555-8555-555555555555';fp.layer=BL_F_Cu
        fp.reference_field.text.value='R2';fp.position=SDKVector.from_xy(2000000,3000000)
        pad=SDKPad();pad.id.value='66666666-6666-4666-8666-666666666666';pad.position=SDKVector.from_xy(2000000,3000000)
        pad.net=SDKNet(name='GND');pad.padstack.layers=[BL_F_Cu];fp.definition.items=[pad]
        return fp
    def test_any_children_remap_without_cache_reverting_and_unknown_nets_block(self):
        board=Board();board.get_enabled_layers=lambda:[BL_F_Cu,BL_B_Cu]
        item=self.sdk_item();plan=live.preview_items(board,[item],'sdk-a');clone=plan.additions[0]
        self.assertEqual(clone.definition.pads[0].id.value,plan.uuid_map[item.definition.pads[0].id.value])
        self.assertNotEqual(clone.id.value,item.id.value)
        self.assertEqual(item.definition.pads[0].id.value,'66666666-6666-4666-8666-666666666666')
        self.assertEqual(live._net_names(clone.proto),{'GND'})
        item.definition.pads[0].net=SDKNet(name='UNKNOWN_PAD_NET')
        with self.assertRaises(live.UnsupportedLiveApply):live.preview_items(board,[item],'sdk-b')
    def test_nested_pad_layer_and_linked_schematic_fail_closed(self):
        board=Board();board.get_enabled_layers=lambda:[BL_F_Cu,BL_B_Cu];item=self.sdk_item()
        item.definition.pads[0].padstack.layers=[BL_In1_Cu]
        with self.assertRaises(live.UnsupportedLiveApply):live.preview_items(board,[item],'sdk-c')
        item=self.sdk_item();item.proto.symbol_path.path.add().value='77777777-7777-4777-8777-777777777777'
        with self.assertRaises(live.UnsupportedLiveApply):live.preview_items(board,[item],'sdk-d')

if __name__=='__main__':unittest.main()
