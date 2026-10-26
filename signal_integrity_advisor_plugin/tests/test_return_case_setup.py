"""Common SI return assignment preserves independent routes and source inputs."""
from copy import deepcopy
import unittest

from signal_integrity_advisor_plugin.return_case_setup import apply_return_nets


class ReturnCaseSetupTests(unittest.TestCase):
    def setUp(self):
        self.cases=[{'id':'data','net':'DATA','start':'U1.1','end':'J1.1','inputs':{
            'rise_ns':1.,'return_nets':['OLD'],'return_terminal_roles':{'source':'X1.1'},'return_terminal_ids':['X1.1']}},
            {'id':'clock','net':'CLOCK','inputs':{'rise_ns':.5}}]

    def test_common_nets_clear_unrelated_pin_roles_without_mutating_source(self):
        original=deepcopy(self.cases);result=apply_return_nets(self.cases,['GND','AGND','GND'])
        self.assertEqual(self.cases,original)
        self.assertEqual(result[0]['start'],'U1.1')
        self.assertEqual(result[0]['inputs'],{'rise_ns':1.,'return_nets':['GND','AGND']})
        self.assertEqual(result[1]['inputs']['rise_ns'],.5)

    def test_off_mode_removes_only_return_inputs(self):
        result=apply_return_nets(self.cases,[])
        self.assertEqual(result[0]['inputs'],{'rise_ns':1.})

    def test_self_return_rejects_every_case_without_partial_update(self):
        original=deepcopy(self.cases)
        with self.assertRaisesRegex(ValueError,'selected return net'):
            apply_return_nets(self.cases,['CLOCK'])
        self.assertEqual(self.cases,original)


if __name__=='__main__':unittest.main()
