"""Dense-board label visibility and incremental pointer interactions."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from quick_therm_plugin.thermal_plot import draw_thermal_view,update_component_hover
from quick_therm_plugin.tests.test_thermal_plot_report import VIEW


def dense_view(count=1024):
    view=copy.deepcopy(VIEW);view['outline_status']='valid'
    view['bbox_mm']=[0,0,100,100];view['outline']=[{'outer_mm':[[0,0],[100,0],[100,100],[0,100]],'holes_mm':[]}]
    view['components']=[]
    for index in range(count):
        x,y=3+3*(index%32),3+3*(index//32)
        view['components'].append({'id':str(index),'reference':f'U{index+1}','position_mm':[x,y],
                                   'bbox_mm':[x-.6,y-.6,x+.6,y+.6],'side':'top','top_side':True,
                                   'in_scope':True,'solved':True,'junction_c':30+index/100,'issues':[]})
    return view


def component_labels(ax):
    return [text for text in ax.texts if text.get_visible() and
            str(text.get_gid()).startswith('quicktherm-component-')]


def pointer(ax,x,y):
    px,py=ax.transData.transform((x,y))
    return SimpleNamespace(inaxes=ax,x=float(px),y=float(py),xdata=x,ydata=y)


class ComponentLabelTests(unittest.TestCase):
    def test_dense_board_keeps_one_selection_and_one_reusable_hover(self):
        figure=Figure(figsize=(8,6));canvas=FigureCanvasAgg(figure);view=dense_view()
        ax=draw_thermal_view(figure,view,selected_id='0');canvas.draw()
        self.assertEqual(len(component_labels(ax)),1)
        self.assertIn('U1 Tj≈30.0°C',component_labels(ax)[0].get_text())
        count=len(ax.texts);limits=(ax.get_xlim(),ax.get_ylim());result=copy.deepcopy(view)
        first=view['components'][1];event=pointer(ax,*first['position_mm'])
        with patch.object(canvas,'draw_idle') as redraw:
            self.assertEqual(update_component_hover(ax,event),'1')
            self.assertEqual(len(component_labels(ax)),2)
            self.assertEqual(update_component_hover(ax,event),'1');redraw.assert_called_once()
            for item in view['components'][2:60]:update_component_hover(ax,pointer(ax,*item['position_mm']))
        self.assertEqual(len(ax.texts),count);self.assertEqual(len(component_labels(ax)),2)
        update_component_hover(ax,pointer(ax,1,99));self.assertEqual(len(component_labels(ax)),1)
        update_component_hover(ax,pointer(ax,3,3));self.assertEqual(len(component_labels(ax)),1)
        update_component_hover(ax,pointer(ax,6,3));update_component_hover(ax)
        self.assertEqual(len(component_labels(ax)),1)
        self.assertEqual((ax.get_xlim(),ax.get_ylim()),limits);self.assertEqual(view,result)

    def test_unselected_and_bottom_views_show_only_the_current_hover(self):
        view=copy.deepcopy(VIEW);figure=Figure(figsize=(5,4));canvas=FigureCanvasAgg(figure)
        ax=draw_thermal_view(figure,view,'Bottom-side map');canvas.draw()
        self.assertEqual(component_labels(ax),[])
        self.assertEqual(update_component_hover(ax,pointer(ax,8,6)),'u2')
        self.assertEqual(component_labels(ax)[0].get_text(),'U2 Tj unknown')
        update_component_hover(ax,SimpleNamespace(inaxes=None,x=0,y=0,xdata=None,ydata=None))
        self.assertEqual(component_labels(ax),[])
        # Top-side selection is not labelled on the opposite side.
        ax=draw_thermal_view(figure,view,'Bottom-side map',selected_id='u1')
        self.assertEqual(component_labels(ax),[])

    def test_hover_uses_current_zoom_and_does_not_rebuild_field(self):
        figure=Figure(figsize=(5,4));canvas=FigureCanvasAgg(figure);view=copy.deepcopy(VIEW)
        network={'board_field':{'x_centers_mm':[2,8],'y_centers_mm':[2,6],'values_c':[[30,31],[32,33]]},
                 'components':[{'reference':'U1','junction_c':42}]}
        ax=draw_thermal_view(figure,view,'Top board model',network=network);canvas.draw()
        before=tuple(ax.collections);ax.set_xlim(1,4);ax.set_ylim(4,1);canvas.draw()
        update_component_hover(ax,pointer(ax,2,2))
        self.assertEqual(component_labels(ax)[0].get_text(),'U1 Tj≈42.0°C')
        self.assertEqual(tuple(ax.collections),before);self.assertEqual(ax.get_xlim(),(1,4));self.assertEqual(ax.get_ylim(),(4,1))

    def test_3d_component_labels_follow_visible_marker_and_rotation(self):
        from mpl_toolkits.mplot3d import proj3d
        figure=Figure(figsize=(6,4));canvas=FigureCanvasAgg(figure)
        ax=draw_thermal_view(figure,copy.deepcopy(VIEW),'3D overview',selected_id='u1');canvas.draw()
        self.assertEqual(len(component_labels(ax)),1)
        for azimuth in (-60,30):
            ax.view_init(elev=28,azim=azimuth);canvas.draw()
            x,y,_=proj3d.proj_transform(8,6,-.8,ax.get_proj());px,py=ax.transData.transform((x,y))
            update_component_hover(ax,SimpleNamespace(inaxes=ax,x=px,y=py,xdata=x,ydata=y))
            self.assertEqual(len(component_labels(ax)),2)
            self.assertIn('U2 Tj unknown',[label.get_text() for label in component_labels(ax)])
            update_component_hover(ax)
        self.assertEqual(len(component_labels(ax)),1)


if __name__=='__main__':unittest.main()
