"""Real native identity preservation across optional KiCad UUID bindings."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch
try:
    import pcbnew as api
except ImportError:
    api=None


class TrackProxy:
    """Expose an actual native track without either optional UUID setter."""
    def __init__(self,native):self.native=native
    def __getattr__(self,name):
        if name in ('SetUuid','SetUuidDirect'):raise AttributeError(name)
        return getattr(self.native,name)
    @property
    def m_Uuid(self):return self.native.m_Uuid
    def Duplicate(self):return type(self)(self.native.Duplicate())


class WritableUuidTrack(TrackProxy):
    @TrackProxy.m_Uuid.setter
    def m_Uuid(self,value):self.native.SetUuidDirect(value)


@unittest.skipIf(api is None,'Native KiCad Python required')
class UuidCompatibilityTests(unittest.TestCase):
    def setUp(self):
        from trace_refiner_plugin.tests.test_native import NativeTests
        self.fixture=NativeTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)

    def test_native_readonly_property_and_setter_free_proxy_clone(self):
        from trace_refiner_plugin.refiner import replacement_track,uid,board_identity
        source=self.fixture.tracks[0];proxy=TrackProxy(source)
        self.assertFalse(hasattr(proxy,'SetUuid'));self.assertFalse(hasattr(proxy,'SetUuidDirect'))
        result=replacement_track(proxy,api,True)
        self.assertIs(type(result),api.PCB_TRACK)
        self.assertEqual(uid(result),uid(source));self.assertNotEqual(board_identity(result),board_identity(source))
        before=tuple(source.GetEnd());result.SetEnd(self.fixture.v(8,4))
        self.assertEqual(tuple(source.GetEnd()),before)

    def test_writable_property_proxy_uses_native_property_assignment(self):
        from trace_refiner_plugin.refiner import replacement_track,uid
        source=self.fixture.tracks[0]
        result=replacement_track(WritableUuidTrack(source),api,True)
        self.assertEqual(uid(result),uid(source))
        self.assertNotEqual(int(result.this),int(source.this))

    def test_native_validate_apply_undo_redo_for_available_setter_paths(self):
        from trace_refiner_plugin.refiner import validate,Transaction,snapshot,connectivity,uid
        source=snapshot(self.fixture.board,api);partitions=connectivity(self.fixture.board,api)
        for path in ('SetUuid','SetUuidDirect','Clone'):
            with self.subTest(path=path),ExitStack() as patches:
                if path!='SetUuid':patches.enter_context(patch.object(api.PCB_TRACK,'SetUuid',None))
                if path=='Clone':patches.enter_context(patch.object(api.PCB_TRACK,'SetUuidDirect',None))
                review=self.fixture.plan();first=uid(review.changes[0].originals[0])
                validate(self.fixture.board,api,review)
                self.assertEqual(review.evidence['new_findings'],0)
                tx=Transaction(self.fixture.board,api,review).redo()
                tracks=list(self.fixture.board.GetTracks())
                self.assertEqual(len(tracks),1);self.assertEqual(uid(tracks[0]),first)
                self.assertEqual(connectivity(self.fixture.board,api),partitions)
                tx.undo();self.assertEqual(snapshot(self.fixture.board,api),source)
                tx.redo();tx.undo();self.assertEqual(snapshot(self.fixture.board,api),source)

    def test_broken_setter_and_unrelated_uuid_collision_fail_before_writes(self):
        from trace_refiner_plugin.refiner import replacement_track,snapshot,check_replacement_ids
        source=snapshot(self.fixture.board,api)
        with patch.object(api.PCB_TRACK,'SetUuid',lambda self,value:None):
            with self.assertRaisesRegex(ValueError,'UUID could not be preserved'):
                replacement_track(self.fixture.tracks[0],api,True)
        self.assertEqual(snapshot(self.fixture.board,api),source)
        review=self.fixture.plan();change=review.changes[0]
        change.added=[replacement_track(change.originals[0],api,True),replacement_track(change.originals[-1],api)]
        change.added[-1].SetUuidDirect(self.fixture.tracks[1].m_Uuid)
        with self.assertRaisesRegex(ValueError,'does not match its source'):
            check_replacement_ids(self.fixture.board,review.changes)
        self.assertEqual(snapshot(self.fixture.board,api),source)


if __name__=='__main__':unittest.main()
