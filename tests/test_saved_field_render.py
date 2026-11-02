"""Execute offline shading against analytical pixels and native colour tables."""
import json
import shutil
import subprocess
import unittest

from wayricad_runtime.field_render import FIELD_SCRIPT, field_palette


NODE = shutil.which('node')
GREY = [[i, i, i, 255] for i in range(256)]


def render(expression, payload):
    code=FIELD_SCRIPT+'\nconst input=JSON.parse(require("fs").readFileSync(0,"utf8"));\n'+expression
    result=subprocess.run([NODE,'-e',code],input=json.dumps(payload),capture_output=True,text=True,timeout=30)
    if result.returncode:raise AssertionError(result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(NODE,'Node runtime required for browser pixel renderer')
class SavedFieldPixels(unittest.TestCase):
    def sample(self, field, cells=False, points=((2,2),(7,7)), grid=False):
        fn='grid' if grid else 'mesh'
        return render('const r=SavedField.'+fn+'(input.field,input.palette,[0,1],input.style,8);'
                      'console.log(JSON.stringify(r&&{bounds:r.bounds,width:r.width,height:r.height,'
                      'pixels:input.points.map(([x,y])=>Array.from(r.pixels.slice(4*(y*r.width+x),4*(y*r.width+x)+4)))}));',
                      {'field':field,'palette':GREY,'style':'cells' if cells else 'smooth','points':points})

    def test_mesh_shades_interior_and_leaves_outside_transparent(self):
        surface={'points':[[0,0],[1,0],[0,1]],'triangles':[[0,1,2]],'values':[0,1,0],'bounds':[0,0,1,1]}
        result=self.sample(surface)
        self.assertEqual(result['pixels'][0],[80,80,80,255])
        self.assertEqual(result['pixels'][1],[0,0,0,0])
        surface['triangles']=[[2,1,0]]
        self.assertEqual(self.sample(surface),result)

    def test_unknown_triangle_stays_empty(self):
        surface={'points':[[0,0],[1,0],[0,1]],'triangles':[[0,1,2]],'values':[0,None,0],'bounds':[0,0,1,1]}
        self.assertEqual(self.sample(surface)['pixels'],[[0,0,0,0],[0,0,0,0]])

    def test_point_grid_gradient_and_missing_corner(self):
        field={'x_centers_mm':[0,1],'y_centers_mm':[0,1],'values_c':[[0,1],[0,1]]}
        result=self.sample(field,grid=True)
        self.assertEqual(result['pixels'][0],[80,80,80,255])
        self.assertEqual(result['pixels'][1],[239,239,239,255])
        field['values_c'][0][0]=None
        self.assertIsNone(self.sample(field,grid=True))

    def test_finite_volume_support_and_raw_cell_choice(self):
        field={'value_location':'finite_volume_cell','x_centers_mm':[.5,1.5],'y_centers_mm':[.5,1.5],
               'x_edges_mm':[0,1,2],'y_edges_mm':[0,1,2],'values_c':[[0,1],[0,1]]}
        smooth=self.sample(field,points=((0,0),(4,3)),grid=True)
        raw=self.sample(field,cells=True,points=((0,0),(4,3)),grid=True)
        self.assertEqual(smooth['bounds'],[0,0,2,2])
        self.assertEqual(smooth['pixels'][0],[0,0,0,255])
        self.assertEqual(smooth['pixels'][1],[159,159,159,255])
        self.assertEqual(raw['pixels'][1],[255,255,255,255])
        field['values_c'][0][0]=None
        self.assertEqual(self.sample(field,points=((0,0),),grid=True)['pixels'][0],[0,0,0,0])

    def test_isolated_point_has_no_invented_area(self):
        field={'x_centers_mm':[0],'y_centers_mm':[0],'values_c':[[.5]]}
        self.assertIsNone(self.sample(field,grid=True))
        field.update(value_location='finite_volume_cell',x_edges_mm=[-.5,.5],y_edges_mm=[-.5,.5])
        self.assertEqual(self.sample(field,grid=True)['pixels'][0],[128,128,128,255])

    def test_colour_interpolation_matches_native_gouraud_instead_of_value_recolouring(self):
        palette=field_palette('inferno')
        surface={'points':[[0,0],[1,0],[0,1]],'triangles':[[0,1,2]],'values':[0,1,0],'bounds':[0,0,1,1]}
        result=render('const r=SavedField.mesh(input.field,input.palette,[0,1],"smooth",8);'
                      'console.log(JSON.stringify(Array.from(r.pixels.slice(72,76))));',{'field':surface,'palette':palette})
        expected=[round((1-2.5/8)*a+(2.5/8)*b) for a,b in zip(palette[0][:3],palette[-1][:3])]+[255]
        for actual,wanted in zip(result,expected):self.assertLessEqual(abs(actual-wanted),1)

    def test_disconnected_mesh_gap_is_not_interpolated(self):
        surface={'points':[[0,0],[1,0],[0,1],[2,0],[3,0],[3,1]],
                 'triangles':[[0,1,2],[3,4,5]],'values':[0,1,0,0,1,1],'bounds':[0,0,3,1]}
        result=render('const r=SavedField.mesh(input,input.palette,[0,1],"smooth",96);'
                      'console.log(JSON.stringify(Array.from(r.pixels.slice(4*(8*r.width+48),4*(8*r.width+48)+4))));',
                      {**surface,'palette':GREY})
        self.assertEqual(result,[0,0,0,0])

    def test_resolution_is_bounded(self):
        field={'x_centers_mm':[0,1],'y_centers_mm':[0,1],'values_c':[[0,1],[0,1]]}
        dimensions=render('const r=SavedField.grid(input,input.palette,[0,1],"smooth",10000);console.log(JSON.stringify([r.width,r.height]));',
                          {**field,'palette':GREY})
        self.assertEqual(dimensions,[2048,2048])


class SavedFieldPalette(unittest.TestCase):
    def test_palette_matches_native_viewport(self):
        from matplotlib import colormaps
        for name in ('inferno','magma','viridis'):
            palette=field_palette(name)
            self.assertEqual(len(palette),256)
            self.assertEqual(palette[0],list(colormaps[name](0.,bytes=True)))
            self.assertEqual(palette[-1],list(colormaps[name](1.,bytes=True)))
