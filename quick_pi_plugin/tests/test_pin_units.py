"""Automatic recommendations must respect physical ownership and total current."""
import unittest

from quick_pi_plugin.pin_units import anchor,peers,unit,validate_units


def terminals():
    return [dict(id=identifier,footprint_uuid=owner,reference=ref,pad_number=number,
                 label=ref+'.'+number,net=net) for identifier,owner,ref,number,net in [
        ('a','connector','J2','1','VCC'),('b','connector','J2','2','VCC'),
        ('c','connector','J2','10','VCC'),('ground','connector','J2','3','GND'),
        ('other','duplicate-ref','J2','4','VCC'),('s','chip','U1','1','VCC'),
        ('t','chip','U1','2','VCC'),('alone','single','R1','1','VCC')]]


class PinUnitTests(unittest.TestCase):
    def test_same_physical_footprint_and_net_in_natural_pin_order(self):
        self.assertEqual([row['id'] for row in peers(terminals(),'a')],['b','c'])
        self.assertEqual([row['id'] for row in peers(terminals(),'s')],['t'])
        self.assertEqual(peers(terminals(),'alone'),[])
        self.assertEqual(peers(terminals(),'a',['b']),[terminals()[2]])

    def test_legacy_or_ambiguous_identity_never_guesses_from_reference(self):
        rows=terminals()
        for row in rows:row.pop('footprint_uuid')
        self.assertEqual(peers(rows,'a'),[])
        self.assertEqual(peers(terminals()+[terminals()[0]],'a'),[])

    def test_current_and_limits_are_for_one_group_not_per_pad(self):
        spec=unit({'terminal':'a','current_A':2.5,'min_voltage_V':3.1},['b','c'])
        self.assertEqual(spec,{'id':'a','terminals':['a','b','c'],'current_A':2.5,'min_voltage_V':3.1})
        self.assertEqual(anchor(spec),'a')
        self.assertNotIn('terminal',spec)
        self.assertEqual(unit({'terminal':'a','current_A':2.5}),{'terminal':'a','current_A':2.5})

    def test_primary_and_additional_sink_units_cannot_claim_same_pad(self):
        validate_units(['a','b'],[unit({'terminal':'s','current_A':1},['t'])])
        for specs in ([{'terminals':['b','s'],'current_A':1}],
                      [{'terminals':['s','t'],'current_A':1},{'terminal':'t','current_A':1}]):
            with self.assertRaisesRegex(ValueError,'shared'):validate_units(['a','b'],specs)


if __name__=='__main__':unittest.main()
