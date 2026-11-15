from types import SimpleNamespace
from trace_impedance_plugin.via_feedback import describe_via,via_notes


def evidence(remaining):
    return {'via_geometry':{'via_type':'through','physical_layers':['F.Cu','In1.Cu','B.Cu'],
        'physical_length_mm':1.5,'connected_path_span':{'start_layer':'F.Cu',
        'end_layer':'In1.Cu','length_mm':.4},'remaining_barrel':remaining}}


def test_stub_lengths_and_unknown_electrical_terms_are_visible_without_guessing():
    section=evidence([{'start_layer':'In1.Cu','end_layer':'B.Cu','length_mm':1.1}])
    text=describe_via(section)
    assert '1.5 mm' in text and '0.4 mm' in text and '1.1 mm' in text
    assert 'not verified' in text and 'unresolved' in text
    assert via_notes(SimpleNamespace(segments=[section,section]))==[text]


def test_full_span_and_bulk_without_endpoints_are_not_claimed_as_open_stubs():
    assert 'No residual barrel' in describe_via(evidence([]))
    assert 'not evaluated' in describe_via(evidence(None))
    assert describe_via({'kind':'track'})==''
