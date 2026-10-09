"""Native 3D display geometry, physical field support and projected picking."""
import copy
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib import colormaps
from mpl_toolkits.mplot3d import proj3d

from quick_therm_plugin.thermal_mesh import board_tiles
from quick_therm_plugin.thermal_plot import (
    _clipped_field_faces, _supported_3d_cells, component_at_event,
    draw_thermal_view, update_component_hover)
from quick_therm_plugin.tests.test_thermal_plot_report import VIEW


def rectangle(x0,y0,x1,y1):
    return [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]


def area(face):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(face,face[1:]+face[:1])))/2


def field(values=None):
    return {'value_location':'finite_volume_cell',
            'x_centers_mm':[2.5,7.5],'y_centers_mm':[2.,6.],
            'x_edges_mm':[0.,5.,10.],'y_edges_mm':[0.,4.,8.],
            'values_c':values if values is not None else [[30.,40.],[50.,60.]]}


def render(view=None,network=None,**kwargs):
    figure=Figure(figsize=(9,6));canvas=FigureCanvasAgg(figure)
    ax=draw_thermal_view(figure,view or copy.deepcopy(VIEW),'3D overview',
                         network=network,viewport=True,**kwargs)
    canvas.draw()
    return figure,canvas,ax


def projected_event(ax,position):
    x,y,_=proj3d.proj_transform(*position,ax.get_proj())
    px,py=ax.transData.transform((x,y))
    return SimpleNamespace(inaxes=ax,x=px,y=py,xdata=x,ydata=y)


class Thermal3DGeometryTests(unittest.TestCase):
    def test_true_contours_preserve_concavity_disjoint_board_and_cutouts(self):
        view={'outline':[
            {'outer_mm':[(0,0),(4,0),(4,1),(1,1),(1,4),(0,4)],
             'holes_mm':[rectangle(.2,2.,.8,3.)]},
            {'outer_mm':rectangle(6,0,8,4),'holes_mm':[]}],
              'drills':[{'contour_mm':rectangle(6.5,1,7.5,2)}]}
        tiles=board_tiles(view)
        self.assertAlmostEqual(sum(map(area,tiles)),7.-.6+8.-1.)
        from quick_therm_plugin.thermal_board_view import _on_board,_inside
        for tile in tiles:
            middle=np.mean(tile,axis=0)
            self.assertTrue(_on_board(middle,view['outline']))
            self.assertFalse(_inside(middle,view['drills'][0]['contour_mm']))
        self.assertFalse(any(_inside((3,3),tile) for tile in tiles))
        self.assertFalse(any(_inside((5,2),tile) for tile in tiles))

    def test_overlapping_drills_and_edge_slot_subtract_the_union(self):
        # Two overlapping 2x2 slots remove six mm²; an edge-crossing drill
        # removes only the part inside the board (one mm²).
        view={'outline':[{'outer_mm':rectangle(0,0,10,8),'holes_mm':[]}],
              'drills':[{'contour_mm':rectangle(2,2,4,4)},
                        {'contour_mm':rectangle(3,2,5,4)},
                        {'contour_mm':[(9,0),(11,0),(10,2)]}]}
        self.assertAlmostEqual(sum(map(area,board_tiles(view))),80.-6.-1.)

    def test_field_cells_clip_small_voids_and_keep_unknown_cells_blank(self):
        view=copy.deepcopy(VIEW)
        view['outline'][0]['holes_mm']=[rectangle(.2,.2,.4,.4)]
        view['drills']=[{'contour_mm':rectangle(1,1,2,2)}]
        faces,values=_clipped_field_faces(field([[30.,None],[50.,np.nan]]),.8,board_tiles(view))
        self.assertEqual(set(values),{30.,50.})
        self.assertAlmostEqual(sum(map(area,faces)),40.-.04-1.)
        self.assertTrue(all(vertex[0]<=5. and vertex[2]==.8 for face in faces for vertex in face))
        from quick_therm_plugin.thermal_board_view import _inside
        for point in ((.3,.3),(1.5,1.5),(7,6)):
            self.assertFalse(any(_inside(point,face) for face in faces))

    def test_point_samples_need_four_known_corners_and_no_half_cell_extent(self):
        samples=field();samples.pop('value_location')
        cells=_supported_3d_cells(samples)
        self.assertEqual(cells,[(2.5,2.,7.5,6.,45.)])
        samples['values_c'][1][1]=None
        self.assertEqual(_supported_3d_cells(samples),[])
        isolated=field([[30.,None],[None,None]])
        self.assertEqual(_supported_3d_cells(isolated),[(0.,0.,5.,4.,30.)])


class Thermal3DResultTests(unittest.TestCase):
    def test_layer_planes_use_all_declared_depths_and_shared_scale(self):
        view=copy.deepcopy(VIEW);view['board_thickness_mm']=1.6
        network={'layers':[{**field(),'name':name,'z_mm':depth}
                            for name,depth in (('F.Cu',.0175),('In1.Cu',.4),('In2.Cu',1.),('B.Cu',1.5825))],
                 'components':[{'reference':'U1','junction_c':None}]}
        original=copy.deepcopy(network)
        figure,_,ax=render(view,network,temperature_limits_c=(20.,80.))
        self.assertEqual([row['side'] for row in ax._thermal_field_planes],['top','internal','internal','bottom'])
        np.testing.assert_allclose([row['z_mm'] for row in ax._thermal_field_planes],[1.5825,1.2,.6,.0175])
        self.assertTrue(all(row['available'] for row in ax._thermal_field_planes))
        self.assertEqual((ax._thermal_norm.vmin,ax._thermal_norm.vmax),(20.,80.))
        self.assertEqual(figure.axes[1].get_ylim(),(20.,80.))
        self.assertIsNone(next(row for row in ax._thermal_targets if row['id']=='u1')['junction_c'])
        self.assertEqual(network,original)

    def test_thin_sheet_is_one_midplane_field_and_missing_thickness_not_invented(self):
        view=copy.deepcopy(VIEW);view['board_thickness_mm']=1.6
        figure,_,ax=render(view,{'board_field':field()})
        self.assertEqual(len(ax._thermal_field_planes),1)
        self.assertEqual(ax._thermal_field_planes[0]['z_mm'],.8)
        self.assertEqual(ax._thermal_field_planes[0]['side'],'midplane')
        self.assertEqual(figure.axes[1].get_ylabel(),'Board midplane °C')
        self.assertTrue(any('one shared thin-sheet field' in text.get_text() for text in ax.texts))
        del view['board_thickness_mm']
        _,_,ax=render(view)
        self.assertFalse(ax._thermal_thickness_known)
        self.assertEqual(ax._thermal_board_z['top'],0.)
        self.assertTrue(any('thickness unknown' in text.get_text() for text in ax.texts))

    def test_viewport_fits_full_extents_aspect_and_retains_report_axes(self):
        for width,height in ((80.,20.),(20.,80.)):
            view=copy.deepcopy(VIEW);view['board_thickness_mm']=1.6
            view['bbox_mm']=[0,0,width,height]
            view['outline']=[{'outer_mm':rectangle(0,0,width,height),'holes_mm':[]}]
            view['components'][0]['bbox_mm']=[-2,0,3,4]
            for azimuth,elevation in ((-60,28),(30,55),(120,-30)):
                _,canvas,ax=render(view,azim=azimuth,elev=elevation)
                self.assertFalse(ax._axis3don)
                self.assertLessEqual(ax.get_xlim()[0],-2.)
                self.assertGreaterEqual(ax.get_xlim()[1],width)
                self.assertGreaterEqual(ax.get_ylim()[0],height)
                extent=(ax.get_xlim()[1]-ax.get_xlim()[0],ax.get_ylim()[0]-ax.get_ylim()[1])
                self.assertAlmostEqual(ax.get_box_aspect()[0]/ax.get_box_aspect()[1],extent[0]/extent[1])
                for x,y in ((-2,0),(width,0),(width,height),(0,height)):
                    event=projected_event(ax,(x,y,1.6))
                    self.assertTrue(ax.bbox.contains(event.x,event.y),(width,height,azimuth,elevation))
        figure=Figure();ax=draw_thermal_view(figure,view,'3D overview')
        self.assertTrue(ax._axis3don)
        self.assertEqual(ax.get_xlabel(),'X mm')

    def test_projected_bounds_pick_and_labels_survive_rotation_and_zoom(self):
        view=copy.deepcopy(VIEW);view['board_thickness_mm']=1.6
        view['components'][1]['bbox_mm']=[6,4,10,8]
        _,canvas,ax=render(view,selected_id='u1')
        labels=lambda:[label for label in ax.texts if label.get_visible() and str(label.get_gid()).startswith('quicktherm-component-')]
        self.assertEqual(len(labels()),1)
        for azimuth,elevation in ((-60,28),(30,45),(120,-30)):
            ax.view_init(elev=elevation,azim=azimuth);canvas.draw()
            event=projected_event(ax,(9.7,7.7,-.8))
            picked=component_at_event(ax,event)
            self.assertEqual(picked['id'],'u2')
            self.assertEqual(picked['side'],'bottom')
            update_component_hover(ax,event)
            self.assertEqual(len(labels()),2)
            self.assertIn('U2 Tj unknown',[label.get_text() for label in labels()])
            update_component_hover(ax)
        ax.set_xlim(5,11);ax.set_ylim(9,3);canvas.draw()
        self.assertEqual(component_at_event(ax,projected_event(ax,(8,6,-.8)))['id'],'u2')

    def test_planar_native_viewport_hides_axes_but_report_retains_units(self):
        figure=Figure();canvas=FigureCanvasAgg(figure)
        ax=draw_thermal_view(figure,copy.deepcopy(VIEW),'Top-side map',viewport=True)
        canvas.draw();self.assertFalse(ax.axison)
        self.assertEqual(ax.get_aspect(),1.)
        ax=draw_thermal_view(figure,copy.deepcopy(VIEW),'Bottom-side map')
        self.assertTrue(ax.axison);self.assertIn('mirrored bottom view',ax.get_xlabel())

    def test_component_result_marker_is_visible_above_board_geometry(self):
        view=copy.deepcopy(VIEW);view['board_thickness_mm']=1.6
        for elevation in (28,-30):
            _,canvas,ax=render(view,elev=elevation)
            target=next(row for row in ax._thermal_targets if row['id']=='u1')
            event=projected_event(ax,target['position'])
            pixels=np.asarray(canvas.buffer_rgba())
            actual=pixels[pixels.shape[0]-1-round(event.y),round(event.x),:3]
            expected=np.asarray(colormaps['inferno'](.5)[:3])*255
            np.testing.assert_allclose(actual,expected,atol=2.)


def _assert_native_geometry(test):
    """The complete saved-board acceptance check, run in a fresh native process."""
    import pcbnew
    from quick_therm_plugin.thermal_board_view import build_board_thermal_view,_inside
    from quick_therm_plugin.tests.test_thermal_board_view import FIXTURE,result
    board=pcbnew.LoadBoard(str(FIXTURE))
    test.assertIsInstance(board,pcbnew.BOARD)
    view=build_board_thermal_view(board,result(),grid_size=12)
    _,_,ax=render(view)
    test.assertEqual(set(row['id'] for row in ax._thermal_targets),
                     set(fp.m_Uuid.AsString() for fp in board.GetFootprints()))
    tiles=board_tiles(view)
    for drill in view['drills']:
        center=np.mean(drill['contour_mm'],axis=0)
        test.assertFalse(any(_inside(center,face) for face in tiles))
    test.assertEqual(ax._thermal_board_z['top'],view['board_thickness_mm'])


class NativeThermal3DTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('pcbnew'),'Native KiCad pcbnew unavailable')
    def test_saved_native_geometry_drills_and_every_footprint_reach_renderer(self):
        # wx frame/service suites share process-global native binding state.
        # On KiCad 10.0.6 a later LoadBoard can return an unwrapped SWIG pointer;
        # never skip or reinterpret that result as a successful geometry check.
        script='''
import sys,unittest
sys.path.insert(0,sys.argv[1])
from quick_therm_plugin.tests.test_thermal_3d import _assert_native_geometry
_assert_native_geometry(unittest.TestCase())
print('Native saved-board 3D geometry passed')
'''
        root=Path(__file__).resolve().parents[2]
        run=subprocess.run([sys.executable,'-B','-I','-c',script,str(root)],
                           stdin=subprocess.DEVNULL,capture_output=True,
                           text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertIn('Native saved-board 3D geometry passed',run.stdout)


if __name__=='__main__':unittest.main()
