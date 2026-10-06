"""Analytical and topology checks for the opt-in volumetric DC model."""
import math
import tempfile
import unittest
from pathlib import Path

from quick_pi_plugin.full3d import VolumeModelError, build_volume_mesh, solve_volume, _polygon_area


def rectangle(x0, y0, x1, y1):
    return {'outer': [[x0,y0],[x1,y0],[x1,y1],[x0,y1]], 'holes': []}


def bar_geometry(length=2., width=1., thickness=.2):
    left=rectangle(0,0,.015,width)
    right=rectangle(length-.015,0,length,width)
    return {'layers':[{'id':0,'name':'F.Cu','z_mm':thickness/2,
                       'thickness_mm':thickness,'polygons':[rectangle(0,0,length,width)]}],
            'terminals':[{'id':'A','label':'J1.1','polygons':{'0':[left]}},
                         {'id':'B','label':'J2.1','polygons':{'0':[right]}}],
            'vias':[], 'geometry_sha256':'synthetic-bar'}


class TetrahedralSolverTests(unittest.TestCase):
    def test_oblique_tetrahedron_exact_affine_potential(self):
        # A sheared tetrahedron checks the full 3D Jacobian, not just box grids.
        mesh={'points_mm':[[0,0,0],[1,0,0],[.3,1,0],[.2,.4,1]],
              'tetrahedra':[[0,1,2,3]]}
        # Two point electrodes on one tetra do not form a uniform bar; check
        # conservation and power, then rotation invariance of the same solid.
        a=solve_volume(mesh,[0],[1])
        mesh['points_mm']=[[z,x,y] for x,y,z in mesh['points_mm']]
        b=solve_volume(mesh,[0],[1])
        self.assertAlmostEqual(a['drop_over_current_ohm'],b['drop_over_current_ohm'],places=11)
        self.assertLess(a['energy_relative_error'],1e-10)
        self.assertLess(a['current_balance_error_A'],1e-9)
        heated=solve_volume(mesh,[0],[1],source_voltage=5.,sink_current=2.,
                            options={'temperature_c':70.})
        scale=1+.00393*50
        self.assertAlmostEqual(heated['drop_over_current_ohm']/a['drop_over_current_ohm'],scale,places=10)
        self.assertAlmostEqual(heated['total_power_W']/a['total_power_W'],4*scale,places=10)
        self.assertAlmostEqual(heated['source_voltage_V'],5.)

    def test_disconnected_copper_rejected(self):
        mesh={'points_mm':[[0,0,0],[1,0,0],[0,1,0],[0,0,1],
                           [3,0,0],[4,0,0],[3,1,0],[3,0,1]],
              'tetrahedra':[[0,1,2,3],[4,5,6,7]]}
        with self.assertRaisesRegex(VolumeModelError,'disconnected'):
            solve_volume(mesh,[0],[4])

    def test_invalid_options_and_overlapping_electrodes(self):
        mesh={'points_mm':[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],'tetrahedra':[[0,1,2,3]]}
        with self.assertRaisesRegex(VolumeModelError,'Unsupported'):
            solve_volume(mesh,[0],[1],options={'frequency_hz':1e6})
        with self.assertRaisesRegex(VolumeModelError,'overlap'):
            solve_volume(mesh,[0],[0])


class NativeGmshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gmsh
        except ImportError:
            raise unittest.SkipTest('Gmsh Python module is unavailable.')

    def test_straight_copper_bar_matches_analytic_dc_resistance(self):
        geometry=bar_geometry()
        mesh=build_volume_mesh(geometry,edge_mm=.5,max_tetrahedra=50000)
        self.assertGreater(mesh['tetrahedron_count'],10)
        self.assertLess(mesh['volume_relative_error'],1e-5)
        result=solve_volume(mesh,mesh['terminal_nodes']['A'],mesh['terminal_nodes']['B'])
        from quick_pi_plugin.volume_view import sampled_cells
        field={'geometry':geometry,'mesh':mesh,'result':result}
        self.assertGreater(sampled_cells(field,'F.Cu','current_density')[2],10)
        self.assertGreater(sampled_cells(field,'F.Cu','voltage')[2],10)
        expected=1.724e-8*(2e-3)/(1e-3*.2e-3)
        self.assertLess(abs(result['drop_over_current_ohm']/expected-1),.05)
        self.assertLess(result['energy_relative_error'],1e-8)
        fine=build_volume_mesh(geometry,edge_mm=.25,max_tetrahedra=50000)
        refined=solve_volume(fine,fine['terminal_nodes']['A'],fine['terminal_nodes']['B'])
        self.assertGreater(fine['tetrahedron_count'],mesh['tetrahedron_count'])
        self.assertLess(abs(result['drop_over_current_ohm']/refined['drop_over_current_ohm']-1),.01)

    def test_dielectric_gap_does_not_connect_copper_layers(self):
        geometry=bar_geometry(length=1.)
        geometry['layers'].append({'id':31,'name':'B.Cu','z_mm':1.1,'thickness_mm':.2,
                                   'polygons':[rectangle(0,0,1,1)]})
        geometry['terminals'][1]['polygons']={'31':[rectangle(.985,0,1,1)]}
        mesh=build_volume_mesh(geometry,edge_mm=.5,max_tetrahedra=50000)
        with self.assertRaisesRegex(VolumeModelError,'disconnected'):
            solve_volume(mesh,mesh['terminal_nodes']['A'],mesh['terminal_nodes']['B'])

    def test_plated_barrel_matches_annular_conductor_reference(self):
        def ring(radius):
            return [[radius*math.cos(i*2*math.pi/32),radius*math.sin(i*2*math.pi/32)] for i in range(32)]
        land={'outer':ring(.35),'holes':[ring(.2)]}
        barrel={'outer':ring(.225),'holes':[ring(.2)]}
        geometry={'layers':[{'id':0,'name':'F.Cu','z_mm':.1,'thickness_mm':.2,'polygons':[land]},
                            {'id':31,'name':'B.Cu','z_mm':1.1,'thickness_mm':.2,'polygons':[land]}],
                  'terminals':[{'id':'A','label':'J1.1','polygons':{'0':[land]}},
                               {'id':'B','label':'J2.1','polygons':{'31':[land]}}],
                  'vias':[{'id':'V1','kind':'via','layers':[0,31],'x_mm':0,'y_mm':0,
                           'drill_mm':.4,'diameters_mm':{'0':.7,'31':.7},
                           'polygons':{'0':[land]}}]}
        mesh=build_volume_mesh(geometry,edge_mm=.1,max_tetrahedra=100000)
        result=solve_volume(mesh,mesh['terminal_nodes']['A'],mesh['terminal_nodes']['B'])
        expected=1.724e-8*(.8e-3)/(_polygon_area(barrel)*1e-6)
        self.assertLess(abs(result['drop_over_current_ohm']/expected-1),.05)
        self.assertLess(result['energy_relative_error'],1e-8)

    def test_refinement_and_barrel_form_one_3d_domain(self):
        geometry=bar_geometry(length=1.,width=1.,thickness=.2)
        bottom={'id':31,'name':'B.Cu','z_mm':1.1,'thickness_mm':.2,
                'polygons':[rectangle(0,0,1,1)]}
        geometry['layers'].append(bottom)
        # A circular drill exclusion is represented by a polygonal hole in
        # each copper face; the plated annulus bridges the two real solids.
        ring=[[.5+.1*math.cos(i*2*math.pi/16),.5+.1*math.sin(i*2*math.pi/16)] for i in range(16)]
        for row in geometry['layers']:
            row['polygons'][0]['holes']=[ring]
        geometry['terminals'][1]['polygons']={'31':[rectangle(.985,0,1,1)]}
        geometry['vias']=[{'id':'V1','kind':'via','layers':[0,31],
                           'x_mm':.5,'y_mm':.5,'drill_mm':.2,
                           'diameters_mm':{'0':.6,'31':.6},
                           'polygons':{'0':[{'outer':[[.5+.3*math.cos(i*2*math.pi/16),
                                                           .5+.3*math.sin(i*2*math.pi/16)] for i in range(16)],
                                              'holes':[ring]}]}}]
        coarse=build_volume_mesh(geometry,edge_mm=.45,max_tetrahedra=150000)
        self.assertTrue(coarse['terminal_nodes']['A'])
        self.assertTrue(coarse['terminal_nodes']['B'])
        result=solve_volume(coarse,coarse['terminal_nodes']['A'],coarse['terminal_nodes']['B'])
        self.assertGreater(result['drop_over_current_ohm'],0)
        self.assertLess(result['energy_relative_error'],1e-7)


class NativeSavedBoardTests(unittest.TestCase):
    def test_saved_board_via_path_runs_end_to_end(self):
        try:
            import gmsh
            import pcbnew as pcb
        except ImportError:
            self.skipTest('Native KiCad Python and Gmsh are required.')
        from quick_pi_plugin.tests.test_board_geometry import BoardGeometryTests
        from quick_pi_plugin.service import execute, run_job
        fixture=BoardGeometryTests('test_zone_voids_and_islands_survive_contact_partition')
        fixture.setUp()
        fixture.override=[{'id':pcb.F_Cu,'z_mm':.1,'thickness_mm':.2},
                          {'id':pcb.B_Cu,'z_mm':1.1,'thickness_mm':.2}]
        fixture.zone(fixture.rectangle(0,0,4,2))
        fixture.zone(fixture.rectangle(0,0,4,2),pcb.B_Cu)
        first=fixture.pad(.5,1)
        second=fixture.pad(3.5,1,number='2')
        back=pcb.LSET();back.AddLayer(pcb.B_Cu);second.SetLayerSet(back)
        via=pcb.PCB_VIA(fixture.board)
        via.SetPosition(fixture.point(2,1));via.SetWidth(pcb.FromMM(.8));via.SetDrill(pcb.FromMM(.4))
        via.SetViaType(pcb.VIATYPE_THROUGH);via.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
        via.SetNet(fixture.net);fixture.board.Add(via)
        with tempfile.TemporaryDirectory(prefix='quick-pi-3d-test-') as directory:
            path=Path(directory)/'test.kicad_pcb'
            pcb.SaveBoard(str(path),fixture.board)
            request={'action':'solve','board_path':str(path),'net':'VCC',
                     'source_terminal':first.m_Uuid.AsString(),
                     'sink_terminal':second.m_Uuid.AsString(),
                     'stackup_override':fixture.override,'model_dimension':'3d',
                     'edge_mm':.35,'plating_mm':.025,
                     'max_tetrahedra':150000,'sink_current':1.}
            before=path.read_bytes()
            output=execute(request)
            self.assertEqual(path.read_bytes(),before)
            self.assertGreater(output['result']['drop_over_current_ohm'],0)
            self.assertLess(output['result']['energy_relative_error'],1e-6)
            worker=run_job(request,timeout=30)
            self.assertEqual(path.read_bytes(),before)
            self.assertAlmostEqual(worker['result']['drop_over_current_ohm'],
                                   output['result']['drop_over_current_ohm'],places=10)


class CliContractTests(unittest.TestCase):
    def test_3d_request_reaches_worker_with_only_supported_options(self):
        from unittest.mock import patch
        from quick_pi_plugin import cli
        from quick_pi_plugin import service
        with tempfile.TemporaryDirectory(prefix='quick-pi-cli-test-') as directory:
            path=Path(directory)/'board.kicad_pcb';path.write_text('(kicad_pcb)',encoding='utf-8')
            sent=[]
            with patch.object(service,'run_job',side_effect=lambda request,timeout: sent.append(request) or {'ok':True}):
                self.assertEqual(cli.main([str(path),'--net','VCC','--source','J1.1','--sink','J2.1',
                                           '--model-dimension','3d','--mesh-edge','.2']),0)
            self.assertEqual(sent[0]['model_dimension'],'3d')
            self.assertEqual(sent[0]['options'],{'temperature_c':20.})

    def test_3d_rejects_2d_only_html_and_vtk(self):
        from quick_pi_plugin import cli
        with tempfile.TemporaryDirectory(prefix='quick-pi-cli-test-') as directory:
            path=Path(directory)/'board.kicad_pcb';path.write_text('(kicad_pcb)',encoding='utf-8')
            base=[str(path),'--net','VCC','--source','J1.1','--sink','J2.1','--model-dimension','3d']
            self.assertEqual(cli.main(base+['--html',str(Path(directory)/'report.html')]),2)
            self.assertEqual(cli.main(base+['--mesh-backend','vtk']),2)


if __name__=='__main__':unittest.main()
