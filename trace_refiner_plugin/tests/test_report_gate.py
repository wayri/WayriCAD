"""Uncapped baseline evidence is required before accepting a native diff."""
import unittest
from trace_refiner_plugin.refiner import new_native_findings, require_comparable_baseline


class ReportGateTests(unittest.TestCase):
    def test_delta_keeps_native_item_ids_and_proposal_association(self):
        def finding(rule, *ids):
            return dict(type=rule,description=rule,severity='error',items=[dict(uuid=identifier) for identifier in ids])
        baseline={'violations':[finding('clearance','original','pad-a')]}
        candidate={'violations':[finding('clearance','new','pad-a'),finding('short','new','pad-b')],
                   'unconnected_items':[finding('unconnected','via','pad-c')]}
        fresh=new_native_findings(baseline,candidate,{'new':'original'},{'new':0})
        self.assertEqual([row['rule'] for row in fresh],['short','unconnected'])
        self.assertEqual(fresh[0]['item_uuids'],['new','pad-b'])
        self.assertEqual(fresh[0]['proposal_indices'],[0])
        self.assertEqual(fresh[1]['proposal_indices'],[])

    def test_delta_preserves_excess_native_rows_with_the_same_item_ids(self):
        row=dict(type='clearance',severity='error',items=[dict(uuid='a'),dict(uuid='b')])
        baseline={'violations':[row]}
        self.assertEqual(len(new_native_findings(baseline,{'violations':[row,row,row]}, {}, {})),2)
        at_one=dict(row,items=[dict(uuid='a',pos=dict(x=1,y=2)),dict(uuid='b')])
        at_two=dict(row,items=[dict(uuid='a',pos=dict(x=2,y=2)),dict(uuid='b')])
        delta=new_native_findings({'violations':[at_one]},{'violations':[at_one,at_two]}, {}, {})
        self.assertEqual(delta[0]['item_positions'],[dict(x=2,y=2)])
        without_id=dict(row,items=[dict(pos=dict(x=1,y=2))])
        moved=dict(row,items=[dict(pos=dict(x=3,y=2))])
        self.assertEqual(len(new_native_findings({'violations':[without_id]},{'violations':[moved]}, {}, {})),1)
        self.assertEqual(len(new_native_findings(baseline,{'unconnected_items':[row]}, {}, {})),1)

    def test_small_baseline_allowed_and_large_per_type_blocked(self):
        require_comparable_baseline(dict(violations=[dict(type='clearance')]*198))
        for category in ('violations','unconnected_items'):
            with self.assertRaisesRegex(ValueError,'Baseline DRC'):
                require_comparable_baseline({category:[dict(type='clearance')]*199})


if __name__=='__main__':unittest.main()
