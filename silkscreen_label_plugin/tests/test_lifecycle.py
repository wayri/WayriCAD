"""Native ownership, report-only legacy handling and atomic cleanup tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_placement as fixture
from silkscreen_label_plugin import lifecycle as m
from silkscreen_label_plugin.placement import GUIDE_PREFIX, NET_PREFIX, item_id, _state
api=fixture.api


class MetadataTests(unittest.TestCase):
    def test_settings_are_bounded_and_do_not_accept_private_paths(self):
        with self.assertRaises(ValueError):m.manifest_value([dict(footprint='bad',text='bad',group=None,leaders=[],settings={})])
        with self.assertRaises(ValueError):m._settings({'board_path':'C:/Private/board.kicad_pcb'})
        with self.assertRaises(ValueError):m._settings({'height':float('nan')})
        with self.assertRaises(ValueError):m._settings({'height':10**1000})
        with self.assertRaises(ValueError):m._settings({'height':'C:/Private'})
        with self.assertRaises(ValueError):m._settings({'reading_direction':'x'*65})


    def test_all_supported_readability_settings_and_36_rotations_are_retained(self):
        settings=dict(preserve_acceptable=True,problem_only=False,
            orientation_preference='Footprint axis',normal_distance=2.0,
            min_width=.6,min_width_ratio=.75,repack_neighbours=6,
            repack_displacement=2.0,leader_limit=10,leader_max_length=3.0,
            allowed_rotations=list(range(0,180,5)))
        self.assertEqual(m._settings(settings),settings)
        for key,value in (('allowed_rotations',list(range(37))),
                ('allowed_rotations',[]),('allowed_rotations',[180]),
                ('preserve_acceptable',1),('problem_only','yes'),
                ('orientation_preference','Automatic'),('normal_distance',0),
                ('min_width',-.1),('min_width_ratio',1.1),
                ('repack_neighbours',13),('repack_neighbours',True),
                ('repack_displacement',-.1),('leader_limit',100001),
                ('leader_limit',1.5),('leader_max_length',0)):
            with self.subTest(key=key,value=value):
                with self.assertRaises(ValueError):m._settings(dict(settings,**{key:value}))
        self.assertEqual(m._settings(dict(repack_neighbours=0,leader_limit=0,repack_displacement=0)),
                         dict(repack_neighbours=0,leader_limit=0,repack_displacement=0))


@unittest.skipIf(api is None,'Native KiCad bindings required')
class LifecycleTests(unittest.TestCase):
    setUp=fixture.PlacementTests.setUp

    def group(self,owner=None,kind=api.SHAPE_T_SEGMENT if api else None):
        owner=owner or self.text;group=api.PCB_GROUP(self.board);group.SetName(GUIDE_PREFIX+item_id(owner))
        line=api.PCB_SHAPE(self.board);line.SetShape(kind);line.SetLayer(api.F_SilkS)
        line.SetStart(self.v(18,18));line.SetEnd(self.v(19,18));line.SetWidth(api.FromMM(.08))
        self.board.Add(line);group.AddItem(line);self.board.Add(group)
        return group,line

    def stamp(self,group):
        self.board.SetProperties(m.generation_properties(self.board,api,[(self.fp,self.text,group)],dict(height=.8,leaders=True)))

    def test_audit_is_read_only_and_legacy_artwork_is_report_only(self):
        group,line=self.group();before=m._fingerprint(self.board,api)
        report=m.audit(self.board,api)
        self.assertEqual(report.findings[0]['status'],'legacy_unverified')
        self.assertFalse(m.plan_cleanup(self.board,api).group_ids)
        self.assertEqual(before,m._fingerprint(self.board,api))
        with self.assertRaisesRegex(ValueError,'uncertain'):m.plan_cleanup(self.board,api,[item_id(group)])

    def test_cleanup_retains_text_and_layout_and_exact_undo_redo(self):
        group,line=self.group();self.stamp(group);before=m._fingerprint(self.board,api);state=_state(self.text)
        self.assertEqual(m.verified_group_ids(self.board,api),{item_id(group)})
        plan=m.plan_cleanup(self.board,api);self.assertEqual(before,m._fingerprint(self.board,api))
        tx=m.apply_cleanup(self.board,api,plan)
        self.assertFalse(any(item_id(i)==item_id(line) for i in self.board.GetDrawings()))
        self.assertFalse(list(self.board.Groups()));self.assertEqual(state,_state(self.text))
        self.assertEqual(m.audit(self.board,api).findings[0]['kind'],'text')
        tx.undo();self.assertEqual(before,m._fingerprint(self.board,api));tx.redo();tx.undo()
        self.assertEqual(before,m._fingerprint(self.board,api))

    def test_planner_guides_become_detached_after_text_or_footprint_moves_and_cleanup_reverses(self):
        from silkscreen_label_plugin.placement import plan,apply
        scratch=Path(__file__).resolve().parents[2]/'.tmp-tests';scratch.mkdir(exist_ok=True)
        for bottom in (False,True):
            with self.subTest(face='bottom' if bottom else 'top'):
                case=fixture.PlacementTests();case.setUp()
                if bottom:case.fp.Flip(case.fp.GetPosition(),False)
                layer=api.B_SilkS if bottom else api.F_SilkS
                preview=plan(case.board,api,dict(leaders=True,leader_distance=.1,normal_distance=.1))
                self.assertEqual(len(preview.changes),1,preview.rejected)
                self.assertTrue(preview.changes[0].leader)
                tx=apply(case.board,api,preview)
                group_id=item_id(tx.groups[0])
                finding=next(row for row in m.audit(case.board,api).findings if row.get('group')==group_id)
                self.assertEqual((finding['status'],finding['attachment']),('managed','attached'))

                with tempfile.TemporaryDirectory(dir=scratch) as directory:
                    path=Path(directory)/'guide.kicad_pcb';api.SaveBoard(str(path),case.board)
                    board=api.LoadBoard(str(path))
                self.assertEqual(next(row for row in m.audit(board,api).findings if row.get('group')==group_id)['status'],'managed')
                fp=next(item for item in board.GetFootprints() if item.GetReference()=='U1')
                text=fp.Reference();self.assertEqual(text.GetLayer(),layer)

                # Move only the text field away from the saved guide.
                text.SetPosition(api.VECTOR2I(api.FromMM(28),api.FromMM(28)))
                moved_text=m._fingerprint(board,api)
                report=m.audit(board,api)
                finding=next(row for row in report.findings if row.get('group')==group_id)
                self.assertEqual(finding['status'],'detached');self.assertTrue(finding['cleanup_eligible'])
                self.assertIn('no longer meet',finding['reason'])
                cleanup=m.apply_cleanup(board,api,m.plan_cleanup(board,api,[group_id]))
                self.assertEqual(text.GetPosition().x,api.FromMM(28))
                cleanup.undo();self.assertEqual(m._fingerprint(board,api),moved_text)

                # Restore the text, then move the owning footprint by itself.
                text.SetPosition(api.VECTOR2I(*preview.changes[0].after[:2]))
                self.assertEqual(next(row for row in m.audit(board,api).findings if row.get('group')==group_id)['status'],'managed')
                fp.Move(api.VECTOR2I(api.FromMM(5),0))
                moved_fp=m._fingerprint(board,api)
                finding=next(row for row in m.audit(board,api).findings if row.get('group')==group_id)
                self.assertEqual(finding['status'],'detached');self.assertTrue(finding['cleanup_eligible'])
                cleanup=m.apply_cleanup(board,api,m.plan_cleanup(board,api,[group_id]))
                cleanup.undo();self.assertEqual(m._fingerprint(board,api),moved_fp)

    def test_metadata_persists_in_native_saved_board(self):
        group,line=self.group();self.stamp(group)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.kicad_pcb';api.SaveBoard(str(path),self.board);loaded=api.LoadBoard(str(path))
            self.assertEqual(m.verified_group_ids(loaded,api),{item_id(group)})
            self.assertTrue(m.plan_cleanup(loaded,api).group_ids)

    def test_orphan_owner_is_reported_and_verified_leaders_can_be_removed(self):
        group,line=self.group();self.stamp(group);self.board.Remove(self.fp)
        report=m.audit(self.board,api)
        self.assertEqual(report.findings[0]['status'],'orphan');self.assertTrue(report.findings[0]['cleanup_eligible'])
        tx=m.apply_cleanup(self.board,api,m.plan_cleanup(self.board,api));self.assertFalse(list(self.board.Groups()));tx.undo()

    def test_changed_members_and_locked_owners_remain_report_only(self):
        group,line=self.group();self.stamp(group);self.fp.SetLocked(True)
        self.assertFalse(m.verified_group_ids(self.board,api));self.fp.SetLocked(False)
        extra=api.PCB_TEXT(self.board);extra.SetText('Manual');self.board.Add(extra);group.AddItem(extra)
        self.assertFalse(m.verified_group_ids(self.board,api));self.assertFalse(m.plan_cleanup(self.board,api).group_ids)
        self.assertIn('members changed',m.audit(self.board,api).findings[0]['reason'])

    def test_manual_nonsegment_is_never_cleanup_eligible(self):
        group,line=self.group(kind=api.SHAPE_T_RECT);self.stamp(group)
        self.assertFalse(m.verified_group_ids(self.board,api))

    def test_duplicate_annotations_reported_and_their_text_retained(self):
        groups=[];texts=[]
        for _ in range(2):
            text=api.PCB_TEXT(self.board);text.SetText('POWER');text.SetLayer(api.F_SilkS);self.board.Add(text)
            group=api.PCB_GROUP(self.board);group.SetName(NET_PREFIX+json.dumps(dict(v=1,footprint=item_id(self.fp),reference=item_id(self.text),visible=True)))
            group.AddItem(text);self.board.Add(group);groups.append(group);texts.append(text)
        report=m.audit(self.board,api)
        self.assertEqual(sum(row['status']=='duplicate' for row in report.findings),2)
        self.assertFalse(m.plan_cleanup(self.board,api).group_ids)
        self.assertEqual(len(list(self.board.GetDrawings())),6)

    def test_duplicate_verified_leader_groups_can_be_cleaned_without_text_loss(self):
        from silkscreen_label_plugin.placement import plan,apply
        preview=plan(self.board,api,dict(leaders=True,leader_distance=.1,normal_distance=.1))
        tx=apply(self.board,api,preview);first=tx.groups[0];line=list(first.GetItems())[0]
        second,line2=self.group()
        line2.SetStart(line.GetStart());line2.SetEnd(line.GetEnd());line2.SetWidth(line.GetWidth());line2.SetLayer(line.GetLayer())
        entries=[(self.fp,self.text,first),(self.fp,self.text,second)]
        self.board.SetProperties(m.generation_properties(self.board,api,entries,preview.settings))
        report=m.audit(self.board,api);self.assertEqual(sum(row['status']=='duplicate' for row in report.findings),2)
        tx=m.apply_cleanup(self.board,api,m.plan_cleanup(self.board,api));self.assertEqual(self.text.GetText(),'U1');tx.undo()

    def test_malformed_metadata_is_read_only_and_blocks_adoption(self):
        group,line=self.group();props=self.board.GetProperties();props[m.MANIFEST_KEY]='{broken';self.board.SetProperties(props)
        self.assertTrue(any(row['kind']=='metadata' for row in m.audit(self.board,api).findings))
        self.assertFalse(m.plan_cleanup(self.board,api).group_ids)
        with self.assertRaisesRegex(ValueError,'uncertain'):m.generation_properties(self.board,api,[(self.fp,self.text,group)],{})

    def test_generation_properties_are_read_only_and_preserve_unrelated_properties(self):
        group,line=self.group();properties=self.board.GetProperties();properties['manual']='keep';self.board.SetProperties(properties)
        before=m._fingerprint(self.board,api)
        candidate=m.generation_properties(self.board,api,[(self.fp,self.text,group)],dict(height=.8))
        self.assertEqual(before,m._fingerprint(self.board,api))
        self.assertEqual(str(candidate['manual']),'keep')
        self.assertIn(m.MANIFEST_KEY,[str(key) for key in candidate.keys()])

    def test_text_only_records_survive_without_generated_graphics(self):
        before=len(list(self.board.GetDrawings()));self.board.SetProperties(m.generation_properties(self.board,api,[(self.fp,self.text,None)],dict(height=.8,selected_only=True)))
        self.assertEqual(before,len(list(self.board.GetDrawings())))
        self.assertEqual(m.audit(self.board,api).findings[0]['status'],'managed')
        self.assertFalse(m.plan_cleanup(self.board,api).group_ids)

    def test_generation_forgets_only_explicitly_removed_text_ids(self):
        other=self.fp.Value()
        self.board.SetProperties(m.generation_properties(self.board,api,
            [(self.fp,self.text,None),(self.fp,other,None)],dict(height=.8)))
        before=m._fingerprint(self.board,api)
        props=m.generation_properties(self.board,api,[],{},removed_text_ids=[item_id(other)])
        self.assertEqual(before,m._fingerprint(self.board,api))
        data=json.loads(str(props[m.MANIFEST_KEY]))
        self.assertEqual([row['text'] for row in data['records']],[item_id(self.text)])
        with self.assertRaises(ValueError):m.generation_properties(self.board,api,[],{},removed_text_ids=['bad'])
        with self.assertRaises(ValueError):m.generation_properties(self.board,api,[],{},removed_text_ids='bad')
        with self.assertRaises(ValueError):m.generation_properties(self.board,api,[],{},removed_text_ids=[item_id(other)]*(m.MAX_RECORDS+1))
        with self.assertRaises(ValueError):m.generation_properties(self.board,api,[(self.fp,other,None)],{},removed_text_ids=[item_id(other)])
        self.assertEqual(before,m._fingerprint(self.board,api))

    def test_stale_apply_and_undo_protect_layout_and_metadata(self):
        group,line=self.group();self.stamp(group);plan=m.plan_cleanup(self.board,api);self.pad.SetSize(self.v(3,3))
        with self.assertRaisesRegex(ValueError,'Board changed'):m.apply_cleanup(self.board,api,plan)
        tx=m.apply_cleanup(self.board,api,m.plan_cleanup(self.board,api));props=self.board.GetProperties();props['manual']='new';self.board.SetProperties(props)
        with self.assertRaisesRegex(ValueError,'Board changed'):tx.undo()

    def test_failure_after_native_remove_rolls_back_atomically(self):
        group,line=self.group();self.stamp(group);before=m._fingerprint(self.board,api);native=self.board.Remove;count=[0]
        def fail(item):
            native(item);count[0]+=1
            if count[0]==1:raise RuntimeError('after removal')
        with patch.object(self.board,'Remove',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'after removal'):m.apply_cleanup(self.board,api,m.plan_cleanup(self.board,api))
        self.assertEqual(before,m._fingerprint(self.board,api))

    def test_failure_after_metadata_write_restores_shapes_members_and_properties(self):
        group,line=self.group();self.stamp(group);before=m._fingerprint(self.board,api);native=self.board.SetProperties;count=[0]
        def fail(props):
            native(props);count[0]+=1
            if count[0]==1:raise RuntimeError('after metadata write')
        with patch.object(self.board,'SetProperties',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'after metadata write'):m.apply_cleanup(self.board,api,m.plan_cleanup(self.board,api))
        self.assertEqual(before,m._fingerprint(self.board,api))

    def test_failed_undo_rolls_back_to_applied_state(self):
        group,line=self.group();self.stamp(group);tx=m.apply_cleanup(self.board,api,m.plan_cleanup(self.board,api));before=m._fingerprint(self.board,api);native=self.board.Add;count=[0]
        def fail(item):
            native(item);count[0]+=1
            if count[0]==1:raise RuntimeError('after add')
        with patch.object(self.board,'Add',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'after add'):tx.undo()
        self.assertEqual(before,m._fingerprint(self.board,api));self.assertTrue(tx.applied)
        tx.undo();self.assertTrue(m.verified_group_ids(self.board,api))


if __name__=='__main__':unittest.main()
