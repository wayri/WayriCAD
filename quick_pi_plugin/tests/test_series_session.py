"""Cross-net session identity, saved setup validation and readable console data."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quick_pi_plugin import setup_file
from quick_pi_plugin.series_editor import parse_saved_path
from quick_pi_plugin.series_session import display_request,restore_endpoints
from quick_pi_plugin.tests.test_series_groups import inventory,saved_path


class Choice:
    def Set(self,values):self.values=list(values)
    def SetSelection(self,index):self.index=index


def series_state():
    request=parse_saved_path(saved_path(),inventory())
    return dict(controls={},net='A',endpoints={'source':'s1','sink':'e1'},
                return_nets=[],return_pads={'source':None,'sink':None},
                extra_sinks=[],package_conduction=[],series_request=request)


def test_cross_net_setup_keeps_all_reviewed_pin_groups_and_old_file_shape():
    state=series_state();before=deepcopy(state)
    frame=SimpleNamespace(inventory=inventory())
    with patch.object(setup_file,'validate_controls'):
        restored=setup_file.validate(frame,state)
    assert restored==before and state==before
    assert restored['series_request']['source_terminals']==['s1','s2']
    assert restored['series_request']['sink_terminals']==['e1','e2']
    assert restored['series_request']['series'][0]['from_pads']==['a1','a2']


def test_cross_net_setup_rejects_wrong_picker_anchor_and_changed_electrode():
    frame=SimpleNamespace(inventory=inventory())
    with patch.object(setup_file,'validate_controls'):
        state=series_state();state['endpoints']['sink']='s2'
        with pytest.raises(ValueError,match='do not match'):setup_file.validate(frame,state)
        state=series_state();state['series_request']['series'][0]['from_pads'].append('gate')
        with pytest.raises(ValueError):setup_file.validate(frame,state)


def test_restore_endpoint_controls_includes_the_other_net_without_uuid_labels():
    frame=SimpleNamespace(inventory=inventory(),source=Choice(),sink=Choice())
    restore_endpoints(frame,series_state()['series_request'])
    assert [row['id'] for row in frame._terminals]==['s1','e1']
    assert frame.source.values==['J1.1','U1.1']
    assert frame.source.index==0 and frame.sink.index==1


def test_console_copy_shows_reference_pins_without_changing_solver_identity():
    request=series_state()['series_request'];before=deepcopy(request)
    visible=display_request(request,inventory())
    assert visible['series'][0]['id']=='Q1'
    assert visible['series'][0]['from_pad']=='Q1.1'
    assert visible['series'][0]['from_pads']==['Q1.1','Q1.2']
    assert request==before and request['series'][0]['from_pad']=='a1'


def test_component_ids_and_duplicate_pad_choices_have_readable_console_aliases():
    rows={'terminals':[dict(id='a',label='Q1.1',reference='Q1',footprint_uuid='component-uuid'),
                       dict(id='b',label='Q1.1',reference='Q1',footprint_uuid='component-uuid')]}
    request={'from_pads':['a','b'],'footprint_uuid':'component-uuid'}
    visible=display_request(request,rows)
    assert visible['footprint_uuid']=='Q1'
    assert visible['from_pads']==['Q1.1 [pad 1/2]','Q1.1 [pad 2/2]']
    assert request['footprint_uuid']=='component-uuid'
