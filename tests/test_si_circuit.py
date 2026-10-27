"""Circuit behavior, input custody and native serialization regression checks."""
import copy
import json
from pathlib import Path
import tempfile
import os
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
import unittest
from unittest import mock

from signal_integrity_advisor_plugin import si_circuit as circuit
from signal_integrity_advisor_plugin.ibis_models import validate_assignment
from wayricad_runtime.schematic_sexpr import parse, properties


IBIS = """[IBIS Ver] 3.2
[File Name] fixture.ibs
[Component] Example
[Manufacturer] Test
[Pin] signal_name model_name
1 TX Driver
2 RX Receiver
[Model] Driver
Model_type Output
[Model] Receiver
Model_type Input
[End]
"""


def report():
    return {"terminal_count": 2,
            "circuit_topology": {"complete": True, "branch_count": 0,
                                 "stub_count": 0, "unmodeled_item_uuids": []},
            "inputs": {}, "blockers": [],
            "path": {"status": "ok", "net_name": "DATA", "start_pad": "U1.1",
                     "end_pad": "U2.2", "length_mm": 20.0, "segments": [
                         {"kind": "track", "geometry": "straight", "layer": "F.Cu",
                          "item_uuid": "a", "start_mm": [0, 0], "end_mm": [10, 0],
                          "length_mm": 10., "resistance_ohm": .1,
                          "copper_thickness_mm": .035, "copper_thickness_source": "saved_stackup",
                          "impedance_ohm": 50., "propagation_delay_ns": .06},
                         {"kind": "track", "geometry": "straight", "layer": "F.Cu",
                          "item_uuid": "b", "start_mm": [20, 0], "end_mm": [10, 0],
                          "length_mm": 10., "resistance_ohm": .2,
                          "copper_thickness_mm": .035, "copper_thickness_source": "saved_stackup",
                          "impedance_ohm": 60., "propagation_delay_ns": .07}]}}


class CircuitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ibis = self.root / "fixture.ibs"
        self.ibis.write_text(IBIS, encoding="ascii")
        self.case = {"id": "data", "report": report(),
                     "source": validate_assignment(self.ibis, "Example", "1", "Driver", "source"),
                     "sink": validate_assignment(self.ibis, "Example", "2", "Receiver", "sink")}

    def export(self, cases=None, options=None):
        return circuit.export_circuit(cases or [self.case], self.root / "bundle", options, guard=lambda: None)

    def test_preserves_each_section_and_native_ibis_and_clipboard(self):
        original = copy.deepcopy(self.case)
        output = self.export()
        self.assertEqual(self.case, original)
        manifest = json.loads(Path(output["manifest"]).read_text(encoding="utf8"))
        blocks = manifest["blocks"]
        self.assertEqual([b["kind"] for b in blocks], ["SOURCE", "R", "LINE", "R", "LINE", "SINK"])
        self.assertEqual([r["item_uuid"] for r in manifest["cases"][0]["sections"]], ["a", "b"])
        self.assertEqual(blocks[2]["nets"][2], blocks[3]["nets"][0])
        self.assertEqual(blocks[4]["nets"][2], blocks[5]["nets"][1])
        self.assertEqual(blocks[0]["fields"]["Sim.Type"], "RECTDRIVER")
        self.assertEqual(blocks[-1]["fields"]["Sim.Type"], "DEVICE")
        self.assertEqual(len(output["model_files"]), 1)
        self.assertEqual(Path(output["model_files"][0]).read_bytes(), self.ibis.read_bytes())
        tree = parse(Path(output["sheets"][0]).read_text(encoding="utf8"))
        symbols = tree.nodes("symbol")
        self.assertEqual(len(symbols), 6)
        self.assertTrue(properties(symbols[0])["Sim.Library"][0].startswith("models/"))
        clip = parse("(selection " + output["clipboard_text"] + ")")
        self.assertEqual(len(clip.nodes("symbol")), 6)
        self.assertFalse(clip.nodes("kicad_sch"))
        self.assertTrue(Path(properties(clip.nodes("symbol")[0])["Sim.Library"][0]).is_absolute())
        self.assertEqual(properties(clip.nodes("symbol")[0])["Sim.Ibis.Pin"][0], "1")

    def test_reviewed_step_is_explicit_tmax_in_schematic_and_clipboard(self):
        output = self.export(options={"duration_ns": 100., "timestep_ns": .025})
        directive = ".tran 0.025n 100n 0 0.025n"
        self.assertIn(directive, Path(output["schematic"]).read_text(encoding="utf8"))
        self.assertIn(directive, output["clipboard_text"])
        manifest = json.loads(Path(output["manifest"]).read_text(encoding="utf8"))
        self.assertEqual(manifest["transient_control"]["directive"], directive)
        self.assertEqual(manifest["transient_control"]["maximum_step_ns"], .025)
        self.assertIn("Adaptive", manifest["transient_control"]["sampling"])

    def test_individual_shunt_branches_preserve_topology_values_and_native_symbols(self):
        self.case['shunt_capacitors'] = [
            dict(id='C_SRC', at='source', capacitance_F=1e-10, esr_ohm=.05, esl_H=1e-9),
            dict(id='C_RX', at='receiver', capacitance_F=1e-9)]
        original = copy.deepcopy(self.case)
        output = self.export()
        self.assertEqual(output['shunt_capacitor_count'],2)
        self.assertEqual(self.case, original)
        manifest = json.loads(Path(output['manifest']).read_text())
        branches = manifest['cases'][0]['shunt_capacitors']
        self.assertEqual([row['id'] for row in branches], ['C_SRC','C_RX'])
        self.assertEqual([len(row['references']) for row in branches], [3,1])
        source = next(row for row in manifest['blocks'] if row['kind']=='SOURCE')['nets'][1]
        receiver = next(row for row in manifest['blocks'] if row['kind']=='SINK')['nets'][1]
        for branch, node in zip(branches, [source, receiver]):
            blocks = [b for b in manifest['blocks'] if b.get('shunt_capacitor_id')==branch['id']]
            self.assertEqual(blocks[0]['nets'][0], node)
            self.assertEqual(blocks[-1]['nets'][1], '0')
            for left, right in zip(blocks, blocks[1:]):self.assertEqual(left['nets'][1], right['nets'][0])
        shunts = [row for row in manifest['blocks'] if row.get('shunt_capacitor_id')=='C_SRC']
        self.assertEqual([row['kind'] for row in shunts], ['R','L','C'])
        self.assertEqual([float(row['value']) for row in shunts], [.05,1e-9,1e-10])
        clip = parse('(selection '+output['clipboard_text']+')')
        self.assertEqual(len(clip.nodes('symbol')), 10)
        for symbol in clip.nodes('symbol'):
            props = properties(symbol)
            if props['Reference'][0] in branches[0]['references']:
                self.assertIn(props['Sim.Device'][0], ('R','L','C'))
                self.assertEqual(props['Sim.Pins'][0], '1=1 2=2')
                self.assertEqual(props['Shunt capacitor ID'][0], 'C_SRC')

    def test_invalid_or_singular_shunt_inputs_are_rejected_before_publication(self):
        for branch in [dict(id='C',at='middle',capacitance_F=1e-9),
                       dict(id='C',at='source',capacitance_F=0),
                       dict(id='C',at='receiver',capacitance_F=float('nan')),
                       dict(id='C',at='source',capacitance_F=1e-9,esl_H=-1e-9),
                       dict(id='C',at='source',capacitance_F=1e-9,unknown=1)]:
            case = copy.deepcopy(self.case);case['shunt_capacitors']=[branch]
            with self.subTest(branch=branch),self.assertRaises(circuit.CircuitExportError):self.export([case])
        case = copy.deepcopy(self.case);case['shunt_capacitors']=[dict(id='C',at='source',capacitance_F=1e-9)]*2
        with self.assertRaisesRegex(circuit.CircuitExportError,'unique'):self.export([case])
        self.assertFalse((self.root/'bundle').exists())

    def test_exported_shunts_have_expected_rc_and_esl_transients_in_native_ngspice(self):
        dll = Path(os.environ.get('WAYRICAD_NGSPICE_DLL',
                    str(Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'KiCad/10.0/bin/ngspice.dll')))
        if not dll.is_file():self.skipTest('Installed ngspice shared library required')
        scenarios = []
        for index, (drive, esr, esl) in enumerate([(50.,0.,0.), (1.,.05,1e-9)]):
            case = copy.deepcopy(self.case)
            case['shunt_capacitors']=[dict(id='C1',at='receiver',capacitance_F=1e-10,esr_ohm=esr,esl_H=esl)]
            output = circuit.export_circuit([case],self.root/('native-'+str(index)),guard=lambda:None)
            model = json.loads(Path(output['manifest']).read_text())
            branch = model['cases'][0]['shunt_capacitors'][0]
            scenarios.append(dict(signal_node=branch['signal_node'],drive_ohm=drive,
                                  blocks=[b for b in model['blocks'] if b.get('shunt_capacitor_id')=='C1']))
        spec = self.root/'passive-check.json';spec.write_text(json.dumps(scenarios))
        helper = Path(__file__).resolve().parents[1]/'signal_integrity_advisor_plugin/tests/ngspice_shunt_check.py'
        run = subprocess.run([sys.executable,str(helper),str(dll),str(spec)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
        data = json.loads(run.stdout.strip().splitlines()[-1])
        expected = 1-math.exp(-(data[0]['sample_time_s']-1.0005e-9)/5e-9)
        self.assertAlmostEqual(data[0]['at_6ns_V'],expected,delta=2e-4)
        damping=1.05/(2*math.sqrt(1e-9/1e-10))
        peak=1+math.exp(-damping*math.pi/math.sqrt(1-damping*damping))
        self.assertAlmostEqual(data[1]['peak_V'],peak,delta=.003)
        self.assertAlmostEqual(data[1]['final_V'],1.,delta=.001)

    def test_native_kicad_netlist_preserves_each_shunt_element_and_return(self):
        executable=Path(os.environ.get('WAYRICAD_KICAD_CLI',
                        str(Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'KiCad/10.0/bin/kicad-cli.exe')))
        if not executable.is_file():self.skipTest('Installed KiCad CLI required')
        self.case['shunt_capacitors']=[dict(id='C_FILTER',at='receiver',capacitance_F=1e-10,esr_ohm=.05,esl_H=1e-9)]
        output=self.export();target=self.root/'native.xml'
        run=subprocess.run([str(executable),'sch','export','netlist','--format','kicadxml',
                            '--output',str(target),output['schematic']],capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
        pins={}
        for net in ET.parse(target).getroot().findall('./nets/net'):
            for node in net.findall('node'):pins[node.attrib['ref'],node.attrib['pin']]=net.attrib['name']
        model=json.loads(Path(output['manifest']).read_text())
        branches=[row for row in model['blocks'] if row.get('shunt_capacitor_id')=='C_FILTER']
        for row in branches:
            self.assertEqual(pins[row['reference'],'1'],row['nets'][0])
            self.assertEqual(pins[row['reference'],'2'],row['nets'][1])

    def test_requires_whole_net_evidence_and_two_terminals(self):
        for change in ({"terminal_count": 3}, {"circuit_topology": {}},
                       {"circuit_topology": {"complete": True, "branch_count": 0, "stub_count": 1, "unmodeled_item_uuids": []}}):
            case = copy.deepcopy(self.case)
            case["report"].update(change)
            with self.assertRaises(circuit.CircuitExportError):
                self.export([case])
        self.assertFalse((self.root / "bundle").exists())

    def test_missing_geometry_unknowns_and_disconnected_sections_rejected(self):
        for change in ({"impedance_ohm": None}, {"propagation_delay_ns": None},
                       {"resistance_ohm": None}, {"item_uuid": ""},
                       {"start_mm": [30, 0], "end_mm": [40, 0]}, {"geometry": "unknown"}):
            case = copy.deepcopy(self.case)
            case["report"]["path"]["segments"][1].update(change)
            with self.assertRaises(circuit.CircuitExportError):
                self.export([case])

    def test_explicit_user_line_assumptions_fill_unknowns(self):
        self.case["report"]["inputs"] = {"assumed_z0_ohm": 75, "assumed_epsilon_eff": 4}
        for section in self.case["report"]["path"]["segments"]:
            section.update(impedance_ohm=None, propagation_delay_ns=None)
        output = self.export()
        sections = json.loads(Path(output["manifest"]).read_text())["cases"][0]["sections"]
        self.assertAlmostEqual(sections[0]["delay_ns"], 20 / 299.792458)
        self.assertEqual(sections[0]["z0_ohm"], 75)

    def test_via_needs_both_manual_terms_and_approximations(self):
        path = self.case["report"]["path"]
        path["length_mm"] = 20.5
        path["segments"][1]["layer"] = "B.Cu"
        path["segments"].insert(1, {"kind": "via", "geometry": "barrel", "layer": "F.Cu", "end_layer": "B.Cu",
                                    "item_uuid": "via", "start_mm": [10, 0], "end_mm": [10, 0],
                                    "length_mm": .5, "resistance_ohm": .02, "inductance_nh": .1})
        for options in ({}, {"allow_approximations": True},
                        {"allow_approximations": True, "via_capacitance_pf": .2}):
            with self.assertRaises(circuit.CircuitExportError):
                self.export(options=options)
        output = self.export(options={"allow_approximations": True, "via_capacitance_pf": .2, "via_inductance_nh": 2})
        manifest = json.loads(Path(output["manifest"]).read_text())
        self.assertEqual(manifest["cases"][0]["sections"][1]["inductance_nh"], 2)
        self.assertEqual([b["value"] for b in manifest["blocks"] if b["kind"] == "L"], ["2n"])

    def test_source_hash_change_and_role_confusion_rejected(self):
        bad = copy.deepcopy(self.case)
        bad["source"] = self.case["sink"]
        with self.assertRaises(circuit.CircuitExportError):
            self.export([bad])
        self.ibis.write_text(IBIS + "|changed")
        with self.assertRaisesRegex(circuit.CircuitExportError, "changed"):
            self.export()

    def test_existing_destination_untouched_and_failed_stage_removed(self):
        target = self.root / "bundle"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("user")
        with self.assertRaises(circuit.CircuitExportError):
            self.export()
        self.assertEqual(marker.read_text(), "user")
        marker.unlink()
        target.rmdir()
        with mock.patch.object(circuit.shutil, "copyfile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.export()
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".quick-si-export-*")))

    def test_changed_input_during_staging_aborts(self):
        real_copy = circuit.shutil.copyfile
        def mutate(*args, **kwargs):
            self.case["report"]["path"]["length_mm"] = 30
            return real_copy(*args, **kwargs)
        with mock.patch.object(circuit.shutil, "copyfile", side_effect=mutate):
            with self.assertRaisesRegex(circuit.CircuitExportError, "reports changed"):
                self.export()
        self.assertFalse((self.root / "bundle").exists())

    def test_independent_cases_unique_nodes_and_one_catalog_read(self):
        second = copy.deepcopy(self.case)
        second["id"] = "clock"
        with mock.patch.object(circuit, "load_ibis", wraps=circuit.load_ibis) as load:
            output = self.export([self.case, second])
        self.assertEqual(load.call_count, 1)
        blocks = json.loads(Path(output["manifest"]).read_text())["blocks"]
        nets = [{n for b in blocks if b["case_id"] == case for n in b["nets"] if n != "0"} for case in ("data", "clock")]
        self.assertFalse(nets[0] & nets[1])

    def test_distinct_exports_cannot_short_signal_nets_when_pasted_together(self):
        first = self.export()
        second = circuit.export_circuit([self.case], self.root / "second-bundle", guard=lambda: None)
        manifests = [json.loads(Path(output["manifest"]).read_text()) for output in (first, second)]
        signals = [{net for block in data["blocks"] for net in block["nets"] if net != "0"}
                   for data in manifests]
        self.assertFalse(signals[0] & signals[1])
        self.assertNotEqual(manifests[0]["signal_net_namespace"], manifests[1]["signal_net_namespace"])
        for output, expected in zip((first, second), signals):
            clip = parse("(selection " + output["clipboard_text"] + ")")
            labels = {label.val() for label in clip.nodes("global_label")}
            self.assertEqual(labels - {"0"}, expected)
            self.assertIn("0", labels)

    def test_invalid_transient_options_rejected(self):
        for options in ({"duty_percent": 100}, {"timestep_ns": 0}, {"frequency_mhz": float("nan")},
                        {"duration_ns": 1e9}, {"allow_approximations": "yes"}, {"unknown": 1}):
            with self.assertRaises(circuit.CircuitExportError):
                self.export(options=options)

    def test_publication_guard_rejects_change_without_leaving_bundle(self):
        guard = mock.Mock(side_effect=[None, ValueError("saved config changed")])
        with self.assertRaisesRegex(ValueError, "saved config changed"):
            circuit.export_circuit([self.case], self.root / "bundle", guard=guard)
        self.assertEqual(guard.call_count, 2)
        self.assertFalse((self.root / "bundle").exists())
        self.assertFalse(list(self.root.glob(".quick-si-export-*")))

    def test_report_source_hash_checks_are_deduplicated_and_repeated(self):
        self.case["report"]["source_fingerprints"] = {"board.kicad_pcb": "example"}
        other = copy.deepcopy(self.case)
        other["id"] = "second"
        with mock.patch("signal_integrity_advisor_plugin.ibis_workflow.require_report_source") as check:
            self.export([self.case, other])
        # A transient Windows sharing lock may cause publication retries; every
        # retry must check source custody again, while each pass deduplicates cases.
        self.assertGreaterEqual(check.call_count, 2)
        self.assertLessEqual(check.call_count, 5)

    def test_all_cases_survive_pagination_and_caption_is_not_spice(self):
        cases = [dict(copy.deepcopy(self.case), id=f"case-{i}") for i in range(8)]
        cases[0]["id"] = ".control\nquit\n.endc"
        output = self.export(cases)
        self.assertEqual(len(output["sheets"]), 2)
        for sheet in output["sheets"]:
            tree = parse(Path(sheet).read_text(encoding="utf8"))
            self.assertLessEqual(len(tree.nodes("symbol")), 36)
            for text in tree.nodes("text"):
                self.assertFalse(text.val().startswith(".control"))
                self.assertNotIn("\nquit", text.val())
        clip = parse("(selection " + output["clipboard_text"] + ")")
        self.assertEqual(len(clip.nodes("symbol")), 48)
        self.assertEqual(len([s for s in clip.nodes("symbol") if properties(s).get("Sim.Device", [None])[0] == "IBIS"]), 16)

    def test_known_zone_terms_are_explicit_pi_and_unknowns_are_rejected(self):
        section = self.case["report"]["path"]["segments"][1]
        section.update(kind="zone", geometry="filled-copper corridor", inductance_nh=3, capacitance_pf=None)
        with self.assertRaises(circuit.CircuitExportError):
            self.export(options={"allow_approximations": True})
        section["capacitance_pf"] = 4
        output = self.export(options={"allow_approximations": True})
        blocks = json.loads(Path(output["manifest"]).read_text())["blocks"]
        self.assertEqual([b["value"] for b in blocks if b["kind"] == "C"], ["2p", "2p"])

    def test_direct_api_requires_explicit_source_custody(self):
        with self.assertRaisesRegex(circuit.CircuitExportError, "custody"):
            circuit.export_circuit([self.case], self.root / "bundle")

    def test_unsaved_thickness_requires_manual_override_and_rescales_r(self):
        section = self.case["report"]["path"]["segments"][0]
        section["copper_thickness_source"] = "assumed_35um"
        with self.assertRaisesRegex(circuit.CircuitExportError, "copper thickness"):
            self.export(options={"allow_approximations": True})
        with self.assertRaisesRegex(circuit.CircuitExportError, "explicit uniform Z0"):
            self.export(options={"copper_thickness_um": 70})
        self.case["report"]["inputs"]["assumed_z0_ohm"] = 75
        with self.assertRaisesRegex(circuit.CircuitExportError, "effective permittivity"):
            self.export(options={"copper_thickness_um": 70})
        self.case["report"]["inputs"]["assumed_epsilon_eff"] = 4
        output = self.export(options={"copper_thickness_um": 70})
        sections = json.loads(Path(output["manifest"]).read_text())["cases"][0]["sections"]
        self.assertAlmostEqual(sections[0]["resistance_ohm"], .05)
        self.assertAlmostEqual(sections[1]["resistance_ohm"], .2)
        self.assertEqual(sections[0]["z0_ohm"], 75)
        self.assertAlmostEqual(sections[0]["delay_ns"], 20 / 299.792458)
        self.assertIn("User-entered", sections[0]["resistance_basis"])


if __name__ == "__main__":
    unittest.main()
