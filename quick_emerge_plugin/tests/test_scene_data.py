import math
import unittest
try:
    import vtk
    from quick_emerge_plugin import scene_data
except ImportError:
    vtk = None

@unittest.skipIf(vtk is None, 'VTK unavailable')
class SceneDataTests(unittest.TestCase):
    def test_published_patch_feed_geometry(self):
        config=dict(substrate_x_mm=80,substrate_y_mm=80,thickness_mm=.76,
                    patch_width_mm=40,patch_length_mm=31.9,feed_width_mm=1.66,
                    inset_width_mm=2.8,inset_length_mm=9,
                    advanced=dict(patch_feed_extension_mm=24.5,patch_offset_y_mm=.45))
        parts,ports=scene_data.geometry_parts(config)
        copper=[shape for category,shape,z,color,opacity in parts if category=='copper' and z==0]
        area=sum(abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(shape['outer_mm'],shape['outer_mm'][1:]+shape['outer_mm'][:1])))/2 for shape in copper)
        self.assertAlmostEqual(area,1266.27)
        self.assertAlmostEqual(ports[0][0][1],-40)
        self.assertAlmostEqual(max(y for shape in copper for x,y in shape['outer_mm']),16.4)

    def test_polygon_hole_area(self):
        data=scene_data.polygon({'outer_mm':[(0,0),(10,0),(10,10),(0,10)],'holes_mm':[[(3,3),(3,7),(7,7),(7,3)]]},0)
        area=0
        for i in range(data.GetNumberOfCells()):
            cell=data.GetCell(i); p=[data.GetPoint(cell.GetPointId(j)) for j in range(3)]
            area+=abs((p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[2][0]-p[0][0])*(p[1][1]-p[0][1]))/2
        self.assertAlmostEqual(area,84)

    def test_log_unknown_faces(self):
        x=[[0,1,2]]*3; y=[[0]*3,[1]*3,[2]*3]; z=[[0]*3]*3
        data,style=scene_data.colored_grid(x,y,z,[[1,2,3],[2,None,4],[3,4,5]],{})
        self.assertEqual(data.GetNumberOfCells(),0)
        data,style=scene_data.colored_grid(x,y,z,[[1,2,3],[2,0,4],[3,4,5]],{'scale':'log','minimum':1,'maximum':10})
        self.assertEqual(data.GetNumberOfCells(),0)
        self.assertEqual(style[:2],(1,10))

    def test_volume_coordinates_and_unknown_log_colors(self):
        volume={'x_mm':[0,2], 'y_mm':[0,3,5], 'z_mm':[1,4],
                'values':[[[1,None],[0,4],[5,6]],[[7,8],[9,10],[11,12]]]}
        data,style=scene_data.colored_points(volume,{'scale':'log','minimum':1,'maximum':12})
        self.assertEqual(data.GetNumberOfPoints(),10)
        self.assertEqual(data.GetNumberOfVerts(),10)
        self.assertEqual(data.GetPoint(0),(0,0,1))
        self.assertEqual(data.GetPoint(5),(2,0,4))
        self.assertEqual(style[:2],(1,12))
        self.assertNotEqual(data.GetPointData().GetScalars().GetTuple3(0),data.GetPointData().GetScalars().GetTuple3(9))
        self.assertNotIn((0,3,1),[data.GetPoint(i) for i in range(data.GetNumberOfPoints())])
        self.assertNotIn((2,0,1),[data.GetPoint(i) for i in range(data.GetNumberOfPoints())])

    def test_advanced_preview_units_and_actual_shapes(self):
        wave=scene_data.preview_geometry({'f_start_hz':8e9,'f_stop_hz':10e9,'advanced':{'study':'waveguide'}})
        self.assertEqual(wave['bounds'],[-11.43,-5.08,0,11.43,5.08,30])
        walls=scene_data.waveguide_walls(wave)
        self.assertEqual(len(walls),4)
        self.assertTrue(all({point[2] for point in face}=={0,30} for face in walls))
        with self.assertRaises(ValueError): scene_data.waveguide_walls(dict(wave,unit='m'))
        strip=scene_data.preview_geometry({'mode':'pcb_line','advanced':{'line_geometry':'stripline_via'}})
        self.assertEqual(strip['via_x_mm'],[-7.5,7.5])
        segments,vias=scene_data.stripline_segments(strip)
        self.assertEqual(len(segments),3); self.assertEqual(len(vias),2)
        self.assertEqual([s[1] for s in segments],[strip['layer_z_mm'][1],strip['layer_z_mm'][2],strip['layer_z_mm'][1]])
        self.assertEqual([v[0] for v in vias],[-7.5,7.5])
        self.assertEqual(vias[0][3],.2)
        array=scene_data.preview_geometry({'substrate_x_mm':150,'advanced':{'study':'array'}})
        self.assertEqual(array['centers_mm'],[[-30,0],[30,0]])
        self.assertEqual(array['patch_size'],[53,52])
