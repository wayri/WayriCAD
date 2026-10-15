"""Count IPC round trips; mocks establish call scaling, not editor timings."""
from collections import Counter
from types import SimpleNamespace
import unittest

from wayricad_runtime.ipc import Board, Net, UnsupportedCapability, read_snapshot, selected_footprints
try:
    from kipy import board_types as sdk_types
except ImportError:
    sdk_types=None


def item(identity, net='SIGNAL'):
    return SimpleNamespace(id=SimpleNamespace(value=identity), net=SimpleNamespace(name=net))


class Transport:
    def __init__(self, count=2000):
        self.calls=Counter()
        self.tracks=[item(str(i), 'NET'+str(i % 20)) for i in range(count)]
        self.selection=self.tracks[:1]
        self.classname='Signals'
        self.reject=False
    def get_nets(self): return [SimpleNamespace(name='NET'+str(i)) for i in range(20)]
    def get_tracks(self): self.calls['tracks']+=1;return list(self.tracks)
    def get_vias(self): self.calls['vias']+=1;return []
    def get_selection(self): self.calls['selection']+=1;return list(self.selection)
    def get_netclass_for_nets(self, nets):
        self.calls['classes']+=1
        if not isinstance(nets,list):nets=[nets]
        return {net.name:SimpleNamespace(name=self.classname) for net in nets}
    def get_item_bounding_box(self,raw):
        self.calls['bounds']+=1
        return SimpleNamespace(pos=SimpleNamespace(x=1,y=2),size=SimpleNamespace(x=3,y=4))
    def add_to_selection(self,items):
        if self.reject:raise RuntimeError('write rejected')
        self.selection.extend(items)
    def remove_from_selection(self,items): self.selection=[x for x in self.selection if x not in items]
    def create_items(self,items): self.tracks.extend(items);return items
    def remove_items(self,items): self.tracks=[x for x in self.tracks if x not in items]
    def update_items(self,items):
        if self.reject:raise RuntimeError('write rejected')
        return items


class IPCPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.raw=Transport()
        self.board=Board(self.raw,SimpleNamespace(Net=lambda name:SimpleNamespace(name=name)))

    def test_large_operation_selection_classes_and_collections_are_bounded(self):
        for track in self.board.GetTracks():
            track.IsSelected()
            track.GetNetClassName()
        self.board.GetSelection()
        self.board.GetTracks()
        self.assertEqual(sum(self.raw.calls.values()),4005)
        self.raw.calls.clear()
        with read_snapshot(self.board):
            for track in self.board.GetTracks():
                track.IsSelected()
                self.assertEqual(track.GetNetClassName(),'Signals')
            self.board.GetSelection()
            self.board.GetTracks()
        self.assertEqual(self.raw.calls,{'tracks':1,'vias':1,'selection':1,'classes':1})

    def test_outside_scope_and_next_operation_observe_new_editor_state(self):
        wrapped=self.board.GetTracks()[0]
        with self.board.read_snapshot():
            self.assertTrue(wrapped.IsSelected())
            self.raw.selection=[]
            self.assertTrue(wrapped.IsSelected())
        self.assertFalse(wrapped.IsSelected())
        with self.board.read_snapshot():self.assertFalse(wrapped.IsSelected())
        self.assertEqual(self.raw.calls['selection'],3)
        Net(self.board,'NET0').GetNetClassName()
        self.raw.classname='Changed'
        self.assertEqual(Net(self.board,'NET0').GetNetClassName(),'Changed')

    def test_nested_scope_and_exception_do_not_leak_to_next_operation(self):
        with self.assertRaisesRegex(RuntimeError,'analysis failed'):
            with self.board.read_snapshot():
                self.board.GetSelection()
                with self.board.read_snapshot():self.board.GetSelection()
                raise RuntimeError('analysis failed')
        self.assertIsNone(self.board._snapshot)
        self.raw.selection=[]
        self.assertEqual(self.board.GetSelection(),[])
        self.assertEqual(self.raw.calls['selection'],2)

    def test_selection_write_invalidates_even_on_rejected_write(self):
        wrapped=self.board.GetTracks()[1]
        with self.board.read_snapshot():
            self.assertFalse(wrapped.IsSelected())
            wrapped.SetSelected()
            self.assertTrue(wrapped.IsSelected())
            self.raw.reject=True
            with self.assertRaises(RuntimeError):wrapped.SetSelected()
            self.raw.selection=[]
            self.assertFalse(wrapped.IsSelected())
        self.assertEqual(self.raw.calls['selection'],3)

    def test_add_remove_and_flush_invalidate_collections_and_bounds(self):
        wrapped=self.board.GetTracks()[0]
        with self.board.read_snapshot():
            self.assertEqual(len(self.board.GetTracks()),2000)
            self.board.Remove(wrapped)
            self.assertEqual(len(self.board.GetTracks()),1999)
            self.board.Add(wrapped)
            self.assertEqual(len(self.board.GetTracks()),2000)
            first=wrapped.GetBoundingBox()
            first.Inflate(100)
            self.assertEqual(wrapped.GetBoundingBox().GetLeft(),1)
            wrapped.flush()
            self.assertEqual(wrapped.GetBoundingBox().GetLeft(),1)
        self.assertEqual(self.raw.calls['bounds'],2)
        self.assertEqual(self.raw.calls['tracks'],4) # One initial, then three operation reads.

    def test_bulk_message_size_is_bounded_and_new_net_is_resolved(self):
        for i in range(1200):self.board.net_id('EXTRA'+str(i))
        with self.board.read_snapshot():
            self.assertEqual(Net(self.board,'NET0').GetNetClassName(),'Signals')
            self.assertEqual(self.raw.calls['classes'],3)
            self.assertEqual(Net(self.board,'NEW').GetNetClassName(),'Signals')
            self.assertEqual(self.raw.calls['classes'],4)

    def test_native_board_helper_is_no_op(self):
        native=object()
        with read_snapshot(native) as board:self.assertIs(board,native)


@unittest.skipIf(sdk_types is None,'kicad-python SDK required')
class SelectionParentTests(unittest.TestCase):
    def test_selected_footprint_polling_uses_one_selection_and_no_parent_scan(self):
        from unittest.mock import Mock
        raw=Mock();raw.get_nets.return_value=[]
        fp=sdk_types.FootprintInstance();fp.id.value='selected';fp.reference_field.text.value='J1'
        pad=sdk_types.Pad();pad.id.value='child';pad.proto.parent.value='different-footprint'
        raw.get_selection.return_value=[fp,pad,sdk_types.Track()]
        board=Board(raw,sdk_types)
        self.assertEqual([item.GetReference() for item in selected_footprints(board)],['J1'])
        raw.get_selection.assert_called_once()
        raw.get_items_by_id.assert_not_called()
        raw.get_footprints.assert_not_called()
        raw.get_selection.return_value=[]
        self.assertEqual(selected_footprints(board),[])


@unittest.skipIf(sdk_types is None,'kicad-python SDK required')
class FingerprintTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.raw=Mock();self.raw.get_nets.return_value=[]
        self.track=sdk_types.Track();self.track.id.value='track'
        self.raw.get_tracks.return_value=[self.track]
        for name in ('get_vias','get_zones','get_footprints','get_shapes','get_text'):
            getattr(self.raw,name).return_value=[]
        self.board=Board(self.raw,sdk_types)

    def fingerprint(self,ignore=()):
        from wayricad_runtime.geometry import board_fingerprint
        return board_fingerprint(self.board,ignore)

    def test_source_check_is_fresh_inside_cached_read_scope(self):
        with self.board.read_snapshot():
            self.board.GetTracks()
            before=self.fingerprint()
            replacement=sdk_types.Track();replacement.id.value='track'
            replacement.width=100000
            self.raw.get_tracks.return_value=[replacement]
            self.assertNotEqual(before,self.fingerprint())
        self.raw.get_tracks.assert_called()
        self.assertEqual(self.raw.get_tracks.call_count,3)
        self.raw.get_item_bounding_box.assert_not_called()

    def test_text_nested_pad_and_zone_changes_are_observed(self):
        fp=sdk_types.FootprintInstance();fp.id.value='footprint'
        pad=sdk_types.Pad();pad.id.value='pad';fp.definition.items=[pad]
        self.raw.get_footprints.return_value=[fp]
        text=sdk_types.BoardText();text.id.value='text'
        self.raw.get_text.return_value=[text]
        zone=sdk_types.Zone();zone.id.value='zone'
        self.raw.get_zones.return_value=[zone]
        before=self.fingerprint()
        pad.number='2'
        after_pad=self.fingerprint();self.assertNotEqual(before,after_pad)
        text.value='New board text'
        after_text=self.fingerprint();self.assertNotEqual(after_pad,after_text)
        zone.proto.name='Changed zone'
        self.assertNotEqual(after_text,self.fingerprint())

    def test_ignored_preview_and_order_are_deterministic(self):
        preview=sdk_types.Track();preview.id.value='preview'
        before=self.fingerprint()
        self.raw.get_tracks.return_value=[preview,self.track]
        self.assertEqual(before,self.fingerprint([self.board.wrap(preview)]))
        first=self.fingerprint()
        self.raw.get_tracks.return_value=[self.track,preview]
        self.assertEqual(first,self.fingerprint())

    def test_transport_failure_never_uses_old_source_digest(self):
        self.fingerprint()
        self.raw.get_tracks.side_effect=RuntimeError('editor unavailable')
        with self.assertRaisesRegex(RuntimeError,'editor unavailable'):
            self.fingerprint()

    def test_four_thousand_item_check_uses_six_bulk_calls_without_bounds(self):
        tracks=[]
        for index in range(4000):
            track=sdk_types.Track();track.id.value=str(index);tracks.append(track)
        self.raw.get_tracks.return_value=tracks
        self.raw.get_item_bounding_box.return_value=SimpleNamespace(
            pos=SimpleNamespace(x=0,y=0),size=SimpleNamespace(x=1,y=1))
        # The former scalar path asks the editor for every item's bounding box.
        for track in self.board.GetTracks():track.GetBoundingBox()
        self.assertEqual(self.raw.get_item_bounding_box.call_count,4000)
        self.raw.reset_mock()
        self.fingerprint()
        calls=sum(getattr(self.raw,name).call_count for name in ('get_tracks','get_vias','get_zones','get_footprints','get_shapes','get_text'))
        self.assertEqual(calls,6)
        self.raw.get_item_bounding_box.assert_not_called()

    def test_native_selected_footprints_keep_flag_semantics(self):
        from unittest.mock import Mock
        selected=Mock();selected.IsSelected.return_value=True
        other=Mock();other.IsSelected.return_value=False
        class NativeBoard:
            def GetFootprints(self):return [selected,other]
        self.assertEqual(selected_footprints(NativeBoard()),[selected])

    def test_selected_pads_resolve_only_selected_parents_in_one_bulk_call(self):
        from unittest.mock import Mock
        raw=Mock()
        raw.get_nets.return_value=[]
        footprints=[];pads=[]
        for index in range(20):
            fp=sdk_types.FootprintInstance();fp.id.value='fp'+str(index)
            fp.reference_field.text.value='J'+str(index)
            footprints.append(fp)
            for number in range(5):
                pad=sdk_types.Pad();pad.id.value='pad'+str(index)+'-'+str(number)
                pad.proto.parent.value=fp.id.value;pad.number=str(number)
                pads.append(pad)
        raw.get_selection.return_value=pads
        raw.get_items_by_id.return_value=footprints
        board=Board(raw,sdk_types)
        with board.read_snapshot():
            selected=board.GetSelection()
            self.assertEqual(len(selected),100)
            self.assertEqual(selected[-1].GetParentFootprint().GetReference(),'J19')
            board.GetSelection()
        raw.get_selection.assert_called_once()
        raw.get_items_by_id.assert_called_once()
        self.assertEqual(len(raw.get_items_by_id.call_args.args[0]),20)
        raw.get_footprints.assert_not_called()

    def test_sdk_field_selection_identity_uses_text_uuid(self):
        from wayricad_runtime.analysis_selection import identity
        first=sdk_types.Field();first.text.id.value='FIRST'
        second=sdk_types.Field();second.text.id.value='SECOND'
        self.assertEqual(identity(first),'first')
        self.assertEqual(identity(second),'second')

    def test_missing_changed_pad_parent_refuses_cached_old_parent_and_recovers(self):
        from unittest.mock import Mock
        raw=Mock();raw.get_nets.return_value=[]
        old=sdk_types.FootprintInstance();old.id.value='old';old.reference_field.text.value='J1'
        new=sdk_types.FootprintInstance();new.id.value='new';new.reference_field.text.value='J2'
        pad=sdk_types.Pad();pad.id.value='pad';pad.proto.parent.value='old'
        raw.get_selection.return_value=[pad];raw.get_items_by_id.return_value=[old]
        board=Board(raw,sdk_types)
        self.assertEqual(board.GetSelection()[0].GetParentFootprint().GetReference(),'J1')
        pad.proto.parent.value='new';raw.get_items_by_id.return_value=[]
        with board.read_snapshot():
            with self.assertRaisesRegex(UnsupportedCapability,'selected pad footprint'):
                board.GetSelection()
            raw.get_items_by_id.return_value=[new]
            self.assertEqual(board.GetSelection()[0].GetParentFootprint().GetReference(),'J2')

    def test_parentless_or_non_footprint_pad_parent_fails_closed(self):
        from unittest.mock import Mock
        raw=Mock();raw.get_nets.return_value=[]
        pad=sdk_types.Pad();pad.id.value='pad'
        raw.get_selection.return_value=[pad]
        board=Board(raw,sdk_types)
        with self.assertRaisesRegex(UnsupportedCapability,'selected pad footprint'):
            board.GetSelection()
        pad.proto.parent.value='not-footprint'
        track=sdk_types.Track();track.id.value='not-footprint'
        raw.get_items_by_id.return_value=[track]
        with self.assertRaisesRegex(UnsupportedCapability,'selected pad footprint'):
            board.GetSelection()


if __name__=='__main__':unittest.main()
