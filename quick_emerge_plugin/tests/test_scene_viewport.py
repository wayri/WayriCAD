import sys
import unittest
try:
    if sys.platform!='win32': raise ImportError()
    import wx
    from quick_emerge_plugin.scene_viewport import SceneViewport
except ImportError:
    wx=None

@unittest.skipIf(wx is None,'Windows wx VTK unavailable')
class SceneViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        self.frame=wx.Frame(None,size=(800,600)); self.events=[]
        self.view=SceneViewport(self.frame,'3D fields',lambda *args:self.events.append(args)); layout=wx.BoxSizer(); layout.Add(self.view,1,wx.EXPAND); self.frame.SetSizer(layout); self.frame.Show(); self.frame.Update(); wx.Yield(); self.view.window.Update()
        self.result={'config':{},'field':{'x_mm':[0,1,2],'y_mm':[0,1,2],'z_mm':2,'frequency_hz':1e9,'norm_e_v_m':[[1,2,3],[2,3,4],[3,4,5]]}}
        self.view.render(lambda *a:None,self.result,reset=True)
    def tearDown(self): self.frame.Destroy(); wx.Yield()
    def test_child_handle_attachment_and_hidden_pages(self):
        frame=wx.Frame(None,size=(700,500)); book=wx.Notebook(frame); layout=wx.BoxSizer(); layout.Add(book,1,wx.EXPAND); frame.SetSizer(layout)
        pages=[SceneViewport(book,'3D setup',lambda *a:None) for _ in range(3)]
        for index,page in enumerate(pages): book.AddPage(page,str(index)); page.render(lambda *a:None,{},reset=True)
        self.assertTrue(all(page.window.GetRenderWindow().GetGenericWindowId() is None for page in pages))
        frame.Show(); frame.Update(); wx.Yield()
        for index,page in enumerate(pages):
            book.SetSelection(index); frame.Layout(); frame.Update(); wx.Yield(); page.refresh_canvas(); page.window.Update(); wx.Yield()
            ident=page.window.GetRenderWindow().GetGenericWindowId()
            self.assertIsNotNone(ident)
            self.assertTrue(page.window.GetRenderWindow().GetInteractor().GetInitialized())
            self.assertTrue(page.window.GetRenderWindow().GetInteractor().GetEnabled())
            self.assertEqual(int(ident.split('_')[1],16), page.window.GetHandle())
        frame.Destroy(); wx.Yield()

    def test_advanced_results_render_actual_descriptors(self):
        view=self.view
        result=dict(self.result)
        result['scene_geometry']={'kind':'sphere','unit':'mm','bounds':[-5,-5,-5,5,5,5],'radius':5}
        view.render(lambda *a:None,result,reset=True,options={'field':False})
        self.assertEqual(view.scene.GetActors().GetNumberOfItems(),1)
        actor=view.scene.GetActors().GetLastActor()
        self.assertGreater(actor.GetMapper().GetInput().GetNumberOfPoints(),100)
        result['scene_geometry']={'kind':'step','unit':'mm','bounds':[-2,-3,-4,2,3,4],'radius':None}
        view.render(lambda *a:None,result,reset=True)
        actor=view.scene.GetActors().GetLastActor()
        self.assertEqual(actor.GetProperty().GetRepresentationAsString(),'Wireframe')
        labels=[view.scene.GetActors2D().GetItemAsObject(i) for i in range(view.scene.GetActors2D().GetNumberOfItems())]
        self.assertTrue(any(hasattr(a,'GetInput') and 'STEP shape unavailable' in (a.GetInput() or '') for a in labels))
        result['scene_geometry']={'kind':'periodic_patch','unit':'mm','cell_size':[30,20],'patch_size':[10,8],'thickness':1,'z_bounds':[-5,5]}
        view.render(lambda *a:None,result,reset=True,options={'field':False})
        self.assertEqual(view.scene.GetActors().GetNumberOfItems(),2)
        result.pop('field')
        result['scene_geometry']={'kind':'thermal_substrate','unit':'mm','bounds':[-2,-2,-1,2,2,0]}
        result['thermal']={'x_mm':[-1,1],'y_mm':[-1,1],'z_mm':0,'temperature_k':[[300,310],[320,330]],'time_s':2}
        view.render(lambda *a:None,result,reset=True,options={})
        labels=[view.scene.GetActors2D().GetItemAsObject(i) for i in range(view.scene.GetActors2D().GetNumberOfItems())]
        self.assertTrue(any(hasattr(a,'GetTitle') and a.GetTitle()=='Temperature [K]' for a in labels))
        self.assertTrue(any(hasattr(a,'GetInput') and 'Temperature [K]' in (a.GetInput() or '') for a in labels))

    def test_derived_quantity_and_step_surface(self):
        import copy
        view=self.view; result=copy.deepcopy(self.result)
        result['field'].update(display_values=[[10,20,30],[20,30,40],[30,40,50]],display_quantity='H magnitude',display_unit='A/m',display_value_key='value_a_m')
        old=copy.deepcopy(result)
        result['scene_geometry']={'kind':'step','unit':'mm','bounds':[0,0,0,1,1,1], 'vertices_mm':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[[0,1,2]]}
        old=copy.deepcopy(result)
        view.render(lambda *a:None,result,reset=True,options={})
        self.assertEqual(result,old)
        actors=view.scene.GetActors(); mesh=actors.GetItemAsObject(0)
        self.assertEqual(mesh.GetMapper().GetInput().GetNumberOfPolys(),1)
        self.assertEqual(mesh.GetProperty().GetRepresentationAsString(),'Surface')
        labels=[view.scene.GetActors2D().GetItemAsObject(i) for i in range(view.scene.GetActors2D().GetNumberOfItems())]
        self.assertTrue(any(hasattr(a,'GetTitle') and a.GetTitle()=='H magnitude [A/m]' for a in labels))
        self.assertTrue(any(hasattr(a,'GetInput') and 'worker-exported STEP surface mesh' in (a.GetInput() or '') for a in labels))
        result['field'].update(display_values=[[0,0,0]]*3,display_quantity='Power flow',display_unit='W/m2',display_value_key='value_w_m2')
        view.render(lambda *a:None,result,reset=True,options={'scale':'log'})
        labels=[view.scene.GetActors2D().GetItemAsObject(i) for i in range(view.scene.GetActors2D().GetNumberOfItems())]
        self.assertTrue(any(hasattr(a,'GetInput') and 'No plottable field data' in (a.GetInput() or '') for a in labels))

    def test_scalar_colors_match_colormap_while_camera_orbits(self):
        import copy
        import vtk
        from matplotlib import colormaps
        view=self.view;result=copy.deepcopy(self.result)
        result['field']['norm_e_v_m']=[[5]*3 for _ in range(3)]
        original=copy.deepcopy(result)
        view.render(lambda *args:None,result,reset=True,options={
            'show_context':False,'copper':False,'ports':False,'minimum':0,'maximum':10,'cmap':'inferno'})
        expected=[int(255*v) for v in colormaps['inferno'](.5)[:3]]
        self.assertEqual(view.data_actor.GetProperty().GetOpacity(),1.)
        self.assertFalse(view.data_actor.GetProperty().GetLighting())
        for preset in ('Top','Isometric'):
            view.set_camera(preset=preset);view.window.Update();wx.Yield();view.window.Render()
            view.scene.SetWorldPoint(1,1,2,1);view.scene.WorldToDisplay()
            x,y,_=view.scene.GetDisplayPoint()
            capture=vtk.vtkWindowToImageFilter();capture.SetInput(view.window.GetRenderWindow())
            capture.SetInputBufferTypeToRGB();capture.ReadFrontBufferOff();capture.Update()
            pixels=capture.GetOutput()
            actual=[pixels.GetScalarComponentAsFloat(round(x),round(y),0,i) for i in range(3)]
            with self.subTest(preset=preset):
                self.assertTrue(all(abs(a-b)<=2 for a,b in zip(actual,expected)),(actual,expected))
        self.assertEqual(result,original)
        # Only the scientific overlays bypass lighting; physical surfaces keep
        # their normal material appearance.
        view.render(options={'field':False,'show_context':True,'copper':True})
        actors=view.scene.GetActors()
        self.assertTrue(all(actors.GetItemAsObject(i).GetProperty().GetLighting()
                            for i in range(actors.GetNumberOfItems())))

    def test_volume_and_radiation_overlays_are_unlit_and_opaque(self):
        view=self.view
        volume={'x_mm':[0,2],'y_mm':[0,2],'z_mm':[1,3],
            'values':[[[1,2],[3,4]],[[5,6],[7,8]]],
            'quantity':'E magnitude','unit':'V/m','value_key':'value_v_m'}
        view._volume(volume)
        self.assertFalse(view.data_actor.GetProperty().GetLighting())
        self.assertEqual(view.data_actor.GetProperty().GetOpacity(),1.)
        view._radiation({'theta_rad':[0,1,2],'phi_rad':[-1,0,1],'norm_e':[[1,1,1],[1,2,1],[1,1,1]]})
        self.assertFalse(view.data_actor.GetProperty().GetLighting())
        self.assertEqual(view.data_actor.GetProperty().GetOpacity(),1.)

    def test_original_volume_render_and_pick(self):
        view=self.view; result=dict(self.result); field=dict(result['field']); result['field']=field
        field['display_volume']={'x_mm':[0,2], 'y_mm':[0,3,5], 'z_mm':[1,4], 'values':[[[1,None],[0,4],[5,6]],[[7,8],[9,10],[11,12]]], 'quantity':'H magnitude','unit':'A/m','value_key':'value_a_m'}
        view.render(lambda *a:None,result,reset=True,options={'field_view':'Volume','scale':'log'})
        actor=view.scene.GetActors().GetLastActor()
        self.assertEqual(actor.GetMapper().GetInput().GetNumberOfVerts(),10)
        row={'kind':'field','x_mm':2,'y_mm':5,'z_mm':4,'ix':1,'iy':2,'iz':1,'value_a_m':12,'unknown':False}
        view.set_samples([row]); view.refresh_canvas(); view.window.Update(); wx.Yield()
        view.scene.SetWorldPoint(2,5,4,1); view.scene.WorldToDisplay(); x,y,_=view.scene.GetDisplayPoint()
        self.assertEqual(view._pick(x,y),row)
        labels=[view.scene.GetActors2D().GetItemAsObject(i) for i in range(view.scene.GetActors2D().GetNumberOfItems())]
        self.assertTrue(any(hasattr(a,'GetTitle') and a.GetTitle()=='H magnitude [A/m]' for a in labels))
        self.assertTrue(any(hasattr(a,'GetInput') and 'volume original samples' in (a.GetInput() or '') for a in labels))
        view.render(options={'field_view':'Volume','field':False})
        self.assertTrue(all(a.GetMapper().GetInput().GetNumberOfVerts()==0 for a in [view.scene.GetActors().GetItemAsObject(i) for i in range(view.scene.GetActors().GetNumberOfItems())]))

    def test_volume_probe_prefers_front_visible_sample(self):
        view=self.view; result=dict(self.result); result['field']=dict(result['field'])
        result['field']['display_volume']={'x_mm':[0,2],'y_mm':[0,2],'z_mm':[1,4],
            'values':[[[1,2],[3,4]],[[5,6],[7,8]]], 'quantity':'E magnitude','unit':'V/m','value_key':'value_v_m'}
        view.render(lambda *args:None,result,reset=True,options={'field_view':'Volume'})
        behind={'kind':'field','x_mm':0,'y_mm':0,'z_mm':1,'value_v_m':1}
        front={'kind':'field','x_mm':0,'y_mm':0,'z_mm':4,'value_v_m':5}
        view.set_samples([behind,front]);view.set_camera(preset='Top');view.window.Update();wx.Yield()
        view.scene.SetWorldPoint(0,0,4,1);view.scene.WorldToDisplay();x,y,_=view.scene.GetDisplayPoint()
        self.assertEqual(view._pick(x,y),front)
        view.render(options={'field':False});self.assertIsNone(view._pick(x,y))

    def test_native_drag_modes(self):
        view=self.view; interactor=view.window; cam=view.scene.GetActiveCamera()
        def drag(mode):
            view.set_mode(mode)
            interactor.SetEventInformation(250,250); interactor.InvokeEvent('LeftButtonPressEvent')
            interactor.SetEventInformation(300,280); interactor.InvokeEvent('MouseMoveEvent')
            interactor.InvokeEvent('LeftButtonReleaseEvent')
        position=cam.GetPosition(); drag('Orbit'); self.assertNotEqual(position,cam.GetPosition())
        focal=cam.GetFocalPoint(); drag('Pan'); self.assertNotEqual(focal,cam.GetFocalPoint())
        scale=cam.GetParallelScale(); drag('Zoom'); self.assertNotEqual(scale,cam.GetParallelScale())
        before=(cam.GetPosition(),cam.GetFocalPoint(),cam.GetParallelScale()); drag('Probe')
        self.assertEqual(before,(cam.GetPosition(),cam.GetFocalPoint(),cam.GetParallelScale()))
        self.assertFalse(any(event[3] for event in self.events))

    def test_toolbar_controls_keep_content_width_on_wide_canvas(self):
        self.frame.SetSize((1500,650));self.frame.Layout();wx.Yield()
        for child in self.view.GetChildren():
            if isinstance(child,wx.Button):
                with self.subTest(button=child.GetLabel()):
                    self.assertLessEqual(child.GetSize().width,child.GetBestSize().width+self.view.FromDIP(4))

    def test_probe_shift_pan_keyboard_and_legend_contrast(self):
        view=self.view;cam=view.scene.GetActiveCamera();interactor=view.window
        view.set_mode('Probe');before=cam.GetFocalPoint()
        interactor.SetEventInformation(250,250,0,1);interactor.InvokeEvent('LeftButtonPressEvent')
        interactor.SetEventInformation(280,270,0,1);interactor.InvokeEvent('MouseMoveEvent')
        interactor.InvokeEvent('LeftButtonReleaseEvent')
        self.assertNotEqual(before,cam.GetFocalPoint())
        self.assertEqual(view.interaction,'Probe')
        self.assertFalse(any(event[3] for event in self.events))
        interactor.SetEventInformation(280,270,0,0)
        view.window.SetFocus();wx.Yield()
        class Key:
            def __init__(self,code):self.code=code
            def GetKeyCode(self):return self.code
            def Skip(self):pass
        view._key(Key(ord('2')))
        self.assertEqual(view.preset_choice.GetStringSelection(),'Top')
        self.assertAlmostEqual(cam.GetDirectionOfProjection()[2],-1)
        view._key(Key(ord('P')));self.assertEqual(view.interaction,'Pan')
        view.set_camera(projection='persp');self.assertTrue(view.projection_button.GetValue())
        self.assertFalse(cam.GetParallelProjection())
        actors=view.scene.GetViewProps()
        bars=[actors.GetItemAsObject(i) for i in range(actors.GetNumberOfItems()) if actors.GetItemAsObject(i).IsA('vtkScalarBarActor')]
        self.assertTrue(bars)
        self.assertLess(max(bars[0].GetLabelTextProperty().GetColor()),.5)
        view.dark=True;view.render();actors=view.scene.GetViewProps()
        bars=[actors.GetItemAsObject(i) for i in range(actors.GetNumberOfItems()) if actors.GetItemAsObject(i).IsA('vtkScalarBarActor')]
        self.assertGreater(min(bars[0].GetLabelTextProperty().GetColor()),.8)

    def test_camera_selection_and_pick(self):
        view=self.view; cam=view.scene.GetActiveCamera(); view.set_camera(preset='Top',projection='ortho'); view.zoom(.85)
        state=(cam.GetPosition(),cam.GetFocalPoint(),cam.GetParallelScale())
        row={'kind':'field','x_mm':1,'y_mm':1,'z_mm':2}; view.set_samples([row]); view.set_selection(row,pins=[row]); view.render(options={'copper':False})
        self.assertEqual(state,(cam.GetPosition(),cam.GetFocalPoint(),cam.GetParallelScale()))
        view.scene.SetWorldPoint(1,1,2,1); view.scene.WorldToDisplay(); x,y,_=view.scene.GetDisplayPoint()
        self.assertEqual(view._pick(x,y),row)
        view.set_mode('Probe'); view.window.SetEventInformation(int(x),int(y)); view._on_press(None,None); view._on_release(None,None)
        self.assertEqual(self.events[-1][2],row)
        view.fit(); self.assertNotEqual(cam.GetParallelScale(),state[2])
        view.set_camera(physical_aspect=False)
