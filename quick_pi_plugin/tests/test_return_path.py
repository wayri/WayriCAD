"""Return-path screening checks that run without native KiCad bindings."""
import unittest

from quick_pi_plugin.return_path import audit_return_path


LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def plane(layer, *, hole=None):
    return {"net": "GND", "layer": layer,
            "outer": [[-1, -1], [11, -1], [11, 2], [-1, 2]],
            "holes": [hole] if hole else []}


def line(layer, start=(0, 0), end=(10, 0)):
    return {"layer": layer, "start": list(start), "end": list(end), "width_mm": .2}


def evidence(**changes):
    data = {"signal_net": "VCC", "return_nets": ["GND"], "layer_order": LAYERS,
            "segments": [line("F.Cu")], "signal_vias": [], "return_vias": [],
            "reference_regions": [plane("In1.Cu")],
            "unfilled_reference_layers": [], "unsupported_geometry": []}
    data.update(changes)
    return data


class ReturnPathTests(unittest.TestCase):
    def test_covered_track_has_no_findings_but_no_proof_claim(self):
        result = audit_return_path(evidence())
        self.assertEqual(result["warning_count"], 0)
        self.assertIn("not a proof", result["basis"])

    def test_hole_crossing_signal_yields_local_gap(self):
        hole = [[4, -.5], [6, -.5], [6, .5], [4, .5]]
        result = audit_return_path(evidence(reference_regions=[plane("In1.Cu", hole=hole)]))
        self.assertEqual([f["code"] for f in result["findings"]], ["REFERENCE_GAP_SAMPLED"])
        self.assertGreaterEqual(result["findings"][0]["position_mm"][0], 4)

    def test_unfilled_zone_is_unknown_instead_of_false_warning(self):
        result = audit_return_path(evidence(reference_regions=[], unfilled_reference_layers=["In1.Cu"]))
        self.assertEqual(result["warning_count"], 0)
        self.assertEqual(result["findings"][0]["level"], "unknown")

    def test_transition_reports_missing_spanning_return_via(self):
        segments = [line("F.Cu", (0, 0), (5, 0)), line("B.Cu", (5, 0), (10, 0))]
        via = {"net": "VCC", "position": [5, 0], "layers": LAYERS}
        data = evidence(segments=segments, signal_vias=[via],
                        reference_regions=[plane("In1.Cu"), plane("In2.Cu")])
        codes = [f["code"] for f in audit_return_path(data)["findings"]]
        self.assertIn("NO_NEARBY_RETURN_VIA", codes)
        data["return_vias"] = [{"net": "GND", "position": [5.5, 0], "layers": LAYERS}]
        codes = [f["code"] for f in audit_return_path(data)["findings"]]
        self.assertNotIn("NO_NEARBY_RETURN_VIA", codes)

    def test_unused_through_via_layers_do_not_create_fake_transition(self):
        via = {"net": "VCC", "position": [5, 0], "layers": LAYERS}
        result = audit_return_path(evidence(signal_vias=[via]))
        self.assertIn("TRANSITION_LAYERS_UNKNOWN", [f["code"] for f in result["findings"]])

    def test_coverage_and_terminals_are_explicit(self):
        data=evidence(terminals=[{'id':'g1','label':'J1.2','net':'GND','position_mm':[0,0],'layers':['F.Cu']},
                                 {'id':'g2','label':'U1.2','net':'GND','position_mm':[10,0],'layers':['F.Cu']}])
        result=audit_return_path(data,return_terminal_ids=['g1','U1.2'],return_terminal_roles={'load':'U1.2'})
        self.assertEqual(result['return_terminal_roles']['load']['id'],'g2')
        self.assertEqual(result['coverage'][0]['covered_sample_count'],41)
        self.assertEqual(result['coverage'][0]['references'],[{'net':'GND','layer':'In1.Cu'}])
        self.assertEqual([r['id'] for r in result['selected_return_terminals']],['g1','g2'])
        self.assertIn('not a solved',result['terminal_connectivity'])
        with self.assertRaises(ValueError):audit_return_path(data,return_terminal_ids=['missing'])
        with self.assertRaises(ValueError):audit_return_path(data,return_terminal_ids=['g1','g1'])

    def test_via_span_does_not_imply_plane_contact(self):
        segments=[line('F.Cu',(0,0),(5,0)),line('B.Cu',(5,0),(10,0))]
        hole=[[5.2,-.8],[6,-.8],[6,.8],[5.2,.8]]
        data=evidence(segments=segments,signal_vias=[{'position':[5,0],'layers':LAYERS}],
                      reference_regions=[plane('In1.Cu'),plane('In2.Cu',hole=hole)],
                      return_vias=[{'net':'GND','position':[5.5,0],'layers':LAYERS}])
        result=audit_return_path(data)
        transition=result['transitions'][0]
        self.assertEqual(transition['nearby_candidates'][0]['sampled_contact_layers'],['In1.Cu'])
        self.assertEqual(transition['status'],'UNKNOWN')
        self.assertIn('RETURN_VIA_CONTACT_UNKNOWN',[r['code'] for r in result['findings']])

    def test_different_reference_nets_do_not_make_closed_return(self):
        other=plane('In2.Cu');other['net']='VREF'
        data=evidence(segments=[line('F.Cu',(0,0),(5,0)),line('B.Cu',(5,0),(10,0))],
                      return_nets=['GND','VREF'],signal_vias=[{'position':[5,0],'layers':LAYERS}],
                      reference_regions=[plane('In1.Cu'),other],return_vias=[{'net':'GND','position':[5.5,0],'layers':LAYERS}])
        result=audit_return_path(data)
        self.assertEqual(result['transitions'][0]['status'],'UNKNOWN')
        self.assertIn('REFERENCE_NET_CHANGE',[r['code'] for r in result['findings']])

    def test_html_escapes_and_preserves_unknown_details(self):
        from wayricad_runtime.return_path import html_details
        data=evidence(signal_net='<signal>');result=audit_return_path(data)
        result['scope']='<script>unsafe</script>'
        html=html_details(result)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
        self.assertIn('source/load return closure is unresolved',html)

    def test_signal_antipad_is_not_filled_in_to_find_reference(self):
        hole=[[4.7,-.3],[5.3,-.3],[5.3,.3],[4.7,.3]]
        data=evidence(segments=[line('F.Cu',(0,0),(5,0)),line('B.Cu',(5,0),(10,0))],
                      signal_vias=[{'position':[5,0],'layers':LAYERS,'diameter_mm':.6}],
                      reference_regions=[plane('In1.Cu',hole=hole),plane('In2.Cu',hole=hole)],
                      return_vias=[{'net':'GND','position':[5.8,0],'layers':LAYERS,'diameter_mm':.3}])
        result=audit_return_path(data);row=result['transitions'][0]
        self.assertEqual(row['reference_probe_radius_mm'],.6)
        self.assertEqual(row['reference_layers'],['In1.Cu','In2.Cu'])
        self.assertEqual(row['status'],'GEOMETRIC_CANDIDATE')
        self.assertIn('REFERENCE_GAP_SAMPLED',[r['code'] for r in result['findings']])
        self.assertIn('no copper is assumed',row['reference_basis'])

    def test_return_via_on_different_island_is_unresolved(self):
        first={'net':'GND','layer':'In2.Cu','outer':[[-1,-1],[5.1,-1],[5.1,2],[-1,2]],'holes':[]}
        second={'net':'GND','layer':'In2.Cu','outer':[[5.3,-1],[11,-1],[11,2],[5.3,2]],'holes':[]}
        data=evidence(segments=[line('F.Cu',(0,0),(5,0)),line('B.Cu',(5,0),(10,0))],
                      signal_vias=[{'position':[5,0],'layers':LAYERS}],reference_regions=[plane('In1.Cu'),first,second],
                      return_vias=[{'net':'GND','position':[5.5,0],'layers':LAYERS}])
        result=audit_return_path(data)
        self.assertEqual(result['transitions'][0]['status'],'UNKNOWN')

    def test_unknown_arc_and_bad_pitch(self):
        result = audit_return_path(evidence(unsupported_geometry=["Arc on F.Cu"]))
        self.assertIn("UNSUPPORTED_GEOMETRY", [f["code"] for f in result["findings"]])
        with self.assertRaises(ValueError):
            audit_return_path(evidence(), sample_pitch_mm=0)


if __name__ == "__main__":
    unittest.main()
