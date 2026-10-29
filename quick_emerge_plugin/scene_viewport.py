"""Hardware-rendered VTK viewport for Quick EMerge 3D scenes."""
from dataclasses import dataclass
from types import SimpleNamespace
import math
import time
import numpy as np
import wx
import vtk
from vtkmodules.wx.wxVTKRenderWindowInteractor import wxVTKRenderWindowInteractor
from . import scene_data
from .field_display import plane_sampling_label, angular_sampling_label

class NativeInteractor(wxVTKRenderWindowInteractor):
    """Initialize VTK only after wx has attached the native child window."""
    def OnPaint(self, event):
        super().OnPaint(event)
        interactor = self.GetRenderWindow().GetInteractor()
        if not interactor.GetInitialized():
            interactor.Initialize()
        if not interactor.GetEnabled():
            interactor.Enable()

@dataclass
class Camera:
    elevation: float = 28
    azimuth: float = -55
    projection: str = 'ortho'
    physical_aspect: bool = True
    roll: float = 0

class SceneViewport(wx.Panel):
    """Native scene with original-sample picking and persistent VTK camera."""
    def __init__(self, parent, name, callback):
        super().__init__(parent)
        self.name, self.callback = name, callback
        self.renderer = self.arguments = None
        self.options = {}; self.dark = False; self.camera = Camera()
        self.figure = self.canvas = None
        self.picking = []; self.markers = []; self.selection = self.profile = None; self.data_actor = None
        self.interaction = 'Orbit'; self._press = None; self._drag_mode = None; self._last_hover = 0; self._initialized = False
        self.scene = vtk.vtkRenderer()
        self.scene.GetActiveCamera().ParallelProjectionOn()
        self.window = NativeInteractor(self, wx.ID_ANY)
        self.window.GetRenderWindow().AddRenderer(self.scene)
        self.window.SetMinSize((1,1))
        self.style = vtk.vtkInteractorStyleTrackballCamera()
        self.window.SetInteractorStyle(self.style)
        self.style.AddObserver('LeftButtonPressEvent', self._on_press)
        self.style.AddObserver('LeftButtonReleaseEvent', self._on_release)
        self.style.AddObserver('MouseMoveEvent', self._on_move)
        self.mode_buttons = {}; bar = wx.WrapSizer(wx.HORIZONTAL, flags=wx.REMOVE_LEADING_SPACES)
        tips={'Orbit':'Orbit [O] · left drag; wheel zoom; Shift + drag pans',
              'Pan':'Pan [P] · left drag; wheel zoom', 'Zoom':'Zoom [Z] · drag; wheel zoom',
              'Probe':'Probe [I] · click an original field sample; Shift + drag pans'}
        for mode in ('Orbit','Pan','Zoom','Probe'):
            button = wx.ToggleButton(self, label=mode, style=wx.BU_EXACTFIT, size=(-1,self.FromDIP(27)))
            button.SetToolTip(tips[mode])
            button.Bind(wx.EVT_TOGGLEBUTTON, lambda event, m=mode: self.set_mode(m))
            self.mode_buttons[mode]=button; bar.Add(button,0,wx.RIGHT|wx.BOTTOM,3)
        for label, tip, action in [('Fit','Fit the whole scene [F] · double-click',self.fit),
                ('+','Zoom in · mouse wheel',lambda:self.zoom(.85)),
                ('−','Zoom out · mouse wheel',lambda:self.zoom(1/.85)),
                ('Image…','Save the current viewport as a PNG',self.export_image)]:
            button=wx.Button(self,label=label,style=wx.BU_EXACTFIT,size=(-1,self.FromDIP(27)))
            button.SetToolTip(tip)
            button.Bind(wx.EVT_BUTTON,lambda event, fn=action:fn()); bar.Add(button,0,wx.RIGHT|wx.BOTTOM,3)
        help_button=wx.Button(self,label='',style=wx.BU_EXACTFIT,size=(self.FromDIP(28),self.FromDIP(27)))
        help_button.SetBitmap(wx.ArtProvider.GetBitmap(wx.ART_HELP,wx.ART_BUTTON,wx.Size(16,16)))
        help_button.SetToolTip('Viewport gestures and keyboard shortcuts')
        help_button.Bind(wx.EVT_BUTTON,self.show_gestures);bar.Add(help_button,0,wx.BOTTOM,3)
        camera_bar=wx.BoxSizer(wx.HORIZONTAL)
        self.preset_choice=wx.Choice(self,choices=['Isometric','Top','Bottom','Front','Right'])
        self.preset_choice.SetSelection(0);self.preset_choice.SetToolTip('Camera preset · keys 1–5')
        self.preset_choice.Bind(wx.EVT_CHOICE,lambda event:self.set_camera(preset=self.preset_choice.GetStringSelection()))
        camera_bar.Add(self.preset_choice,0,wx.RIGHT,5)
        self.projection_button=wx.ToggleButton(self,label='Ortho',style=wx.BU_EXACTFIT)
        self.projection_button.SetToolTip('Orthographic / perspective projection')
        self.projection_button.Bind(wx.EVT_TOGGLEBUTTON,lambda event:self.set_camera(projection='persp' if self.projection_button.GetValue() else 'ortho'))
        camera_bar.Add(self.projection_button,0,wx.RIGHT,8)
        self.hint=wx.StaticText(self,label='',style=wx.ST_ELLIPSIZE_END);self.hint.SetMinSize((1,-1));self.hint.SetForegroundColour('#637382')
        camera_bar.Add(self.hint,1,wx.ALIGN_CENTER_VERTICAL)
        layout=wx.BoxSizer(wx.VERTICAL);layout.Add(bar,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP,5)
        layout.Add(camera_bar,0,wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM,5);layout.Add(self.window,1,wx.EXPAND);self.SetSizer(layout)
        self.Bind(wx.EVT_CHAR_HOOK,self._key)
        self.window.Bind(wx.EVT_LEFT_DCLICK,lambda event:self.fit())
        self.Bind(wx.EVT_SIZE,self._resize)
        self.window.Bind(wx.EVT_WINDOW_DESTROY,self._destroy_window)
        self.set_mode('Orbit')
        self.clear()

    def _destroy_window(self,event):
        if event.GetEventObject() is self.window:
            if hasattr(self,'orientation'): self.orientation.SetEnabled(0)
            render_window=self.window.GetRenderWindow()
            if render_window.GetGenericWindowId():
                self.scene.RemoveAllViewProps()
                render_window.Finalize()
        event.Skip()

    def _resize(self,event):
        wx.CallAfter(self.refresh_canvas); event.Skip()

    def refresh_canvas(self):
        if not self or self.IsBeingDeleted() or not self.IsShownOnScreen(): return
        # wxVTK's paint handler attaches its child HWND before allowing Render.
        self.window.Refresh(False)
        self.window.Render()

    def _actor(self,data,color=None,opacity=1,wire=False):
        mapper=vtk.vtkPolyDataMapper(); mapper.SetInputData(data)
        actor=vtk.vtkActor(); actor.SetMapper(mapper)
        if color is not None: actor.GetProperty().SetColor(*color); mapper.ScalarVisibilityOff()
        actor.GetProperty().SetOpacity(opacity)
        if wire: actor.GetProperty().SetRepresentationToWireframe(); actor.GetProperty().SetLineWidth(1)
        self.scene.AddActor(actor); return actor

    def _scalar_actor(self,data):
        # Scientific colors encode numerical values, not scene illumination.
        # Keep geometry shaded, but draw analytics with the legend's RGB and
        # full opacity so orbiting cannot darken or blend the selected value.
        actor=self._actor(data)
        actor.GetProperty().LightingOff()
        return actor

    def _line(self,a,b,color,width=3):
        line=vtk.vtkLineSource(); line.SetPoint1(*a); line.SetPoint2(*b); line.Update()
        actor=self._actor(line.GetOutput(),color); actor.GetProperty().SetLineWidth(width); return actor

    def _geometry(self, config, region):
        parts,ports=scene_data.geometry_parts(config,region)
        for category,shape,z,color,opacity in parts:
            if self.options.get(category,True): self._actor(scene_data.polygon(shape,z),color,opacity)
        if self.options.get('ports',True):
            for a,b in ports: self._line(a,b,(.94,.25,.39),4)

    def _advanced_geometry(self, descriptor, region=None, config=None):
        if descriptor.get('unit') != 'mm': raise ValueError('Scene geometry must use mm')
        kind=descriptor['kind']
        if kind=='waveguide':
            if self.options.get('copper',True):
                for wall in scene_data.waveguide_walls(descriptor): self._actor(scene_data.face(wall),(.67,.72,.78),.35)
        elif kind=='stripline_via':
            b=descriptor['bounds']; x0,y0,z0,x1,y1,z1=b; base=scene_data.rectangle(x0,y0,x1-x0,y1-y0)
            if self.options.get('show_context',True): self._actor(scene_data.polygon(base,(z0+z1)/2),(.13,.53,.42),.15)
            if self.options.get('copper',True):
                self._actor(scene_data.polygon(base,z0),(.72,.54,.27),.55); self._actor(scene_data.polygon(base,z1),(.72,.54,.27),.25)
                segments,vias=scene_data.stripline_segments(descriptor)
                for shape,z in segments: self._actor(scene_data.polygon(shape,z),(.95,.7,.22))
                for x,zlo,zhi,radius in vias:
                    cylinder=vtk.vtkCylinderSource(); cylinder.SetCenter(x,0,(zlo+zhi)/2); cylinder.SetRadius(radius); cylinder.SetHeight(zhi-zlo); cylinder.SetResolution(24)
                    # VTK cylinder axis is Y; rotate around its center to align with board Z.
                    cylinder.SetCenter(0,0,0); cylinder.Update(); transform=vtk.vtkTransform(); transform.Translate(x,0,(zlo+zhi)/2); transform.RotateX(90)
                    filt=vtk.vtkTransformPolyDataFilter(); filt.SetTransform(transform); filt.SetInputConnection(cylinder.GetOutputPort()); filt.Update(); self._actor(filt.GetOutput(),(.95,.7,.22))
        elif kind=='patch_array':
            sx,sy=descriptor['substrate_size']; th=descriptor['thickness']; w,l=descriptor['patch_size']; base=scene_data.rectangle(-sx/2,-sy/2,sx,sy)
            if self.options.get('show_context',True): self._actor(scene_data.polygon(base,-th/2),(.13,.53,.42),.3)
            if self.options.get('copper',True):
                self._actor(scene_data.polygon(base,-th),(.72,.54,.27))
                c=config or {}; feed=c.get('feed_width_mm'); slot=c.get('inset_width_mm'); inset=c.get('inset_length_mm')
                for x,y in descriptor['centers_mm']:
                    if feed and slot and inset:
                        rects=[scene_data.rectangle(x-w/2,y-l/2+inset,w,l-inset),scene_data.rectangle(x-w/2,y-l/2,w/2-feed/2-slot,inset),scene_data.rectangle(x+feed/2+slot,y-l/2,w/2-feed/2-slot,inset),scene_data.rectangle(x-feed/2,y-l/2,feed,inset)]
                    else: rects=[scene_data.rectangle(x-w/2,y-l/2,w,l)]
                    for shape in rects: self._actor(scene_data.polygon(shape,0),(.85,.66,.32))
            if self.options.get('ports',True):
                for x,y in descriptor['centers_mm']: self._line((x,y-l/2,-th),(x,y-l/2,0),(.94,.25,.39),4)
        elif kind=='periodic_patch':
            sx,sy=descriptor['cell_size']; w,length=descriptor['patch_size']; th=descriptor['thickness']
            if self.options.get('show_context',True):
                self._actor(scene_data.polygon(scene_data.rectangle(-sx/2,-sy/2,sx,sy),-th/2),(.13,.53,.42),.3)
            if self.options.get('copper',True):
                self._actor(scene_data.polygon(scene_data.rectangle(-w/2,-length/2,w,length),0),(.85,.66,.32))
        elif kind=='sphere' and self.options.get('copper',True):
            bounds=descriptor['bounds']; sphere=vtk.vtkSphereSource(); sphere.SetRadius(descriptor['radius'])
            sphere.SetCenter(*[(bounds[i]+bounds[i+3])/2 for i in range(3)])
            sphere.SetThetaResolution(48); sphere.SetPhiResolution(32); sphere.Update(); self._actor(sphere.GetOutput(),(.8,.65,.36))
        elif kind=='step' and descriptor.get('vertices_mm') and descriptor.get('triangles') and self.options.get('copper',True):
            mesh=scene_data.triangle_mesh(descriptor['vertices_mm'],descriptor['triangles'])
            self._actor(mesh,(.8,.65,.36))
        elif kind=='step' and descriptor.get('bounds') and self.options.get('show_context',True):
            b=descriptor['bounds']; cube=vtk.vtkCubeSource(); cube.SetBounds(b[0],b[3],b[1],b[4],b[2],b[5]); cube.Update()
            self._actor(cube.GetOutput(),(.7,.55,.3),wire=True)
        elif kind=='thermal_substrate' and self.options.get('show_context',True):
            if region:
                th=region['substrate']['thickness_mm']
                for shape in region['substrate']['outline']:
                    self._actor(scene_data.polygon(shape,-th/2),(.13,.53,.42),.3)
            else:
                b=descriptor['bounds']; cube=vtk.vtkCubeSource(); cube.SetBounds(b[0],b[3],b[1],b[4],b[2],b[5]); cube.Update(); self._actor(cube.GetOutput(),(.13,.53,.42),.3)

    def _scalarbar(self,style,title):
        lo,hi,mode,cmap=style
        lut=vtk.vtkLookupTable(); lut.SetNumberOfTableValues(256); lut.SetRange(lo,hi)
        if mode=='log': lut.SetScaleToLog10()
        for i in range(256): lut.SetTableValue(i,*cmap(i/255))
        lut.Build(); bar=vtk.vtkScalarBarActor(); bar.SetLookupTable(lut); bar.SetTitle(title); bar.SetNumberOfLabels(4); bar.SetWidth(.12); bar.SetHeight(.65)
        bar.GetTitleTextProperty().ShadowOff(); bar.GetLabelTextProperty().ShadowOff()
        foreground=(.87,.91,.94) if self.dark else (.15,.21,.27)
        bar.GetTitleTextProperty().SetColor(*foreground);bar.GetTitleTextProperty().SetFontSize(12)
        bar.GetLabelTextProperty().SetColor(*foreground);bar.GetLabelTextProperty().SetFontSize(11)
        bar.SetLabelFormat('%.3g');self.scene.AddViewProp(bar)

    def _field(self,field,thermal=False):
        xs,ys=field['x_mm'],field['y_mm']; x=[xs for _ in ys]; y=[[v]*len(xs) for v in ys]; z=[[field['z_mm']]*len(xs) for _ in ys]
        data,style=scene_data.colored_grid(x,y,z,field.get('display_values',field['temperature_k' if thermal else 'norm_e_v_m']),self.options)
        if data is None:
            text=vtk.vtkTextActor(); text.SetInput('No plottable field data'); text.SetPosition(15,35); self.scene.AddViewProp(text); return
        self.data_actor=self._scalar_actor(data)
        if self.options.get('mesh',False): self._actor(data,(.8,.8,.8),wire=True)
        self._scalarbar(style,f"{field.get('display_quantity', 'Temperature' if thermal else '|E|')} [{field.get('display_unit', 'K' if thermal else 'V/m')}]")

    def _volume(self,volume):
        data,style=scene_data.colored_points(volume,self.options)
        if data is None:
            text=vtk.vtkTextActor(); text.SetInput('No plottable volume samples'); text.SetPosition(15,35); self.scene.AddViewProp(text); return
        actor=self._scalar_actor(data); self.data_actor=actor; actor.GetProperty().SetPointSize(4)
        self._scalarbar(style,f"{volume['quantity']} [{volume['unit']}]")

    def _radiation(self,field):
        values=field['norm_e']; peak=max(max(row) for row in values)
        if not math.isfinite(peak) or peak<=0: raise ValueError('Radiation field is empty or non-finite')
        r=[[v/peak for v in row] for row in values]; t,p=field['theta_rad'],field['phi_rad']
        x=[[r[j][i]*math.sin(theta)*math.cos(phi) for i,phi in enumerate(p)] for j,theta in enumerate(t)]
        y=[[r[j][i]*math.sin(theta)*math.sin(phi) for i,phi in enumerate(p)] for j,theta in enumerate(t)]
        z=[[r[j][i]*math.cos(theta) for i,phi in enumerate(p)] for j,theta in enumerate(t)]
        data,style=scene_data.colored_grid(x,y,z,r,self.options,True)
        if data is not None:
            self.data_actor=self._scalar_actor(data)
            if self.options.get('mesh',False): self._actor(data,(.8,.8,.8),wire=True)
            self._scalarbar(style,'Relative |E| (0–1)')

    def render(self,renderer=None,arguments=None,*,reset=False,options=None):
        if renderer is not None: self.renderer,self.arguments=renderer,arguments
        if options is not None: self.options=dict(options)
        if self.renderer is None: return
        camera=vtk.vtkCamera(); camera.DeepCopy(self.scene.GetActiveCamera())
        self.scene.RemoveAllViewProps(); self.data_actor=None; self.scene.SetBackground(*((.065,.11,.16) if self.dark else (.965,.975,.985)))
        a=self.arguments
        if self.name=='3D setup':
            region=a if 'substrate' in a and 'copper' in a else None
            descriptor=scene_data.preview_geometry(a) if region is None else None
            if descriptor: self._advanced_geometry(descriptor,config=a)
            else: self._geometry(a if region is None else {},region)
        elif self.name=='3D fields':
            descriptor=a.get('scene_geometry')
            if descriptor: self._advanced_geometry(descriptor,a.get('region'),a['config'])
            else: self._geometry(a['config'],a.get('region'))
            if self.options.get('field',True):
                if 'thermal' in a: self._field(a['thermal'],thermal=True)
                elif 'field' in a:
                    field=a['field']; volume=field.get('display_volume')
                    if self.options.get('field_view','Plane')=='Volume' and volume: self._volume(volume)
                    else: self._field(field)
        elif self.name=='3D radiation':
            if self.options.get('field',True) and 'radiation' in a: self._radiation(a['radiation'])
        self._markers()
        self._labels(a)
        if reset:
            self.scene.ResetCamera(); self._preset('Isometric'); self.scene.ResetCamera()
        else: self.scene.GetActiveCamera().DeepCopy(camera)
        self.scene.ResetCameraClippingRange(); self.refresh_canvas()

    def _labels(self, arguments):
        text=vtk.vtkTextActor()
        if self.name == '3D setup':
            label='PCB region: clipped saved copper; exterior board omitted' if 'substrate' in arguments else 'Template geometry: PCB context only; no board copper imported'
        elif self.name == '3D fields':
            if 'thermal' in arguments:
                field=arguments['thermal']; label=f"Temperature [K] | Z={field['z_mm']:g} mm | time={field['time_s']:g} s | substrate only"
            else:
                field=arguments['field']; label=f"{field.get('display_quantity', '|E|')} [{field.get('display_unit', 'V/m')}] | Z={field['z_mm']:g} mm | {field['frequency_hz']/1e9:g} GHz | solver excitation"
        else:
            label='Relative far-field |E|: normalized radius; not gain, efficiency or physical distance'
            if 'radiation' not in arguments: label='Radiation surface is available for the patch model.'
        if self.name=='3D fields':
            sampled=arguments.get('thermal',arguments.get('field'))
            volume=arguments.get('field',{}).get('display_volume')
            if self.options.get('field_view','Plane')=='Volume' and volume:
                label+='\n'+f"{len(volume['x_mm'])}×{len(volume['y_mm'])}×{len(volume['z_mm'])} original volume samples"
            elif sampled:label+='\n'+plane_sampling_label(sampled)
        elif self.name=='3D radiation' and 'radiation' in arguments:
            label+='\n'+angular_sampling_label(arguments['radiation'])
        descriptor=arguments.get('scene_geometry',{}) if isinstance(arguments,dict) else {}
        if self.name=='3D setup' and not descriptor and 'config' not in arguments and 'substrate' not in arguments:
            descriptor=scene_data.preview_geometry(arguments) or {}
        if descriptor.get('kind')=='step':
            if descriptor.get('vertices_mm') and descriptor.get('triangles'): label += ' | worker-exported STEP surface mesh'
            else: label += ' | STEP shape unavailable; bounds only' if descriptor.get('bounds') else ' | STEP shape unavailable until solved; no geometry shown'
        if descriptor.get('kind')=='periodic_patch': label += ' | periodic unit cell'
        if descriptor.get('kind')=='waveguide': label += ' | hollow waveguide; open ports'
        if descriptor.get('kind')=='stripline_via': label += ' | four-layer internal trace and ideal solid vias'
        if descriptor.get('kind')=='patch_array': label += ' | finite patch array'
        if self.name=='3D fields' and self.options.get('field_view','Plane')=='Volume' and arguments.get('field',{}).get('display_volume'):
            label += ' | volume original samples'
        if self.options.get('mesh',False): label += ' | sample grid'
        text.SetInput(label); text.SetPosition(12,12); prop=text.GetTextProperty(); prop.SetFontSize(13)
        prop.SetColor(*((.87,.91,.94) if self.dark else (.15,.21,.27))); self.scene.AddViewProp(text)
        axes=vtk.vtkAxesActor(); axes.SetTotalLength(10,10,10); axes.SetXAxisLabelText('X [mm]'); axes.SetYAxisLabelText('Y [mm]'); axes.SetZAxisLabelText('Z [mm]')
        if self.name=='3D radiation':
            axes.SetXAxisLabelText('X'); axes.SetYAxisLabelText('Y'); axes.SetZAxisLabelText('Z'); axes.SetTotalLength(.2,.2,.2)
        # Orientation marker is overlaid in display coordinates, independent of scene bounds.
        if not hasattr(self,'orientation'):
            self.orientation=vtk.vtkOrientationMarkerWidget(); self.orientation.SetInteractor(self.window); self.orientation.SetViewport(0,.78,.16,1)
        self.orientation.SetOrientationMarker(axes); self.orientation.SetEnabled(1); self.orientation.InteractiveOff()

    def clear(self):
        self.scene.RemoveAllViewProps(); self.data_actor=None; self.renderer=self.arguments=None; self.picking=[]; self.markers=[]; self.selection=self.profile=None
        self.scene.SetBackground(*((.065,.11,.16) if self.dark else (.965,.975,.985)))
        self.mode_buttons['Probe'].Disable()
        message=vtk.vtkTextActor(); message.SetInput('Preview geometry to begin.' if self.name=='3D setup' else 'Run a simulation to load this result view.')
        message.SetPosition(24,32); message.GetTextProperty().SetColor(.25,.3,.35); message.GetTextProperty().SetFontSize(16)
        self.scene.AddViewProp(message); self.refresh_canvas()

    def _preset(self,name):
        directions={'Isometric':(1,-1,.8),'Top':(0,0,1),'Bottom':(0,0,-1),'Front':(0,-1,0),'Right':(1,0,0)}
        direction=directions[name]; cam=self.scene.GetActiveCamera(); focal=cam.GetFocalPoint(); distance=cam.GetDistance() or 1
        norm=math.sqrt(sum(v*v for v in direction)); cam.SetPosition(*(focal[i]+distance*direction[i]/norm for i in range(3)))
        cam.SetViewUp(0,1,0) if name in ('Top','Bottom') else cam.SetViewUp(0,0,1)

    def set_camera(self,*,preset=None,projection=None,physical_aspect=None):
        cam=self.scene.GetActiveCamera()
        if preset:
            self._preset(preset)
            self.preset_choice.SetStringSelection(preset)
        if projection:
            self.camera.projection=projection; cam.SetParallelProjection(projection=='ortho')
            self.projection_button.SetValue(projection=='persp');self.projection_button.SetLabel('Persp' if projection=='persp' else 'Ortho')
        if physical_aspect is not None:
            self.camera.physical_aspect=physical_aspect
            transform=vtk.vtkMatrix4x4()
            transform.SetElement(2,2,1 if physical_aspect or self.name=='3D radiation' else 4)
            cam.SetModelTransformMatrix(transform)
        self.scene.ResetCameraClippingRange(); self.refresh_canvas()

    def fit(self): self.scene.ResetCamera(); self.refresh_canvas()
    def zoom(self,scale):
        cam=self.scene.GetActiveCamera(); cam.SetParallelScale(cam.GetParallelScale()*scale) if cam.GetParallelProjection() else cam.Dolly(1/scale)
        self.scene.ResetCameraClippingRange(); self.refresh_canvas()
    def set_samples(self,rows):
        self.picking=rows
        self.mode_buttons['Probe'].Enable(bool(rows))
        self._sample_points=np.asarray([row['display_xyz'] if 'display_xyz' in row else (row['x_mm'],row['y_mm'],row['z_mm']) for row in rows],dtype=float).reshape((-1,3))
    def set_mode(self,mode):
        if mode not in self.mode_buttons: raise ValueError('Unknown viewport interaction mode')
        self.interaction=mode
        self._press=None;self._drag_mode=None
        for key,button in self.mode_buttons.items(): button.SetValue(key==mode)
        self.hint.SetLabel(('Hover · click original sample' if self.picking else 'No field samples in this view') if mode=='Probe' else 'Drag to '+mode.lower()+' · wheel zoom · Shift drag pan')
        self.window.SetCursor(wx.Cursor(wx.CURSOR_CROSS if mode=='Probe' else wx.CURSOR_HAND))
        self.window.SetFocus()

    def _pick(self,x,y):
        if not self.picking or self.data_actor is None: return None
        width,height=self.window.GetRenderWindow().GetSize()
        if not width or not height: return None
        # VTK resolves depth on the actual plotted dataset. Screen-only nearest
        # neighbors can select an invisible sample on the back of a surface.
        picker=vtk.vtkPointPicker(); picker.PickFromListOn(); picker.AddPickList(self.data_actor)
        picker.SetTolerance(14/math.hypot(width,height))
        if not picker.Pick(x,y,0,self.scene) or picker.GetPointId()<0: return None
        position=np.asarray(picker.GetPickPosition())
        distance=np.sum((self._sample_points-position)**2,axis=1)
        index=int(np.argmin(distance))
        return self.picking[index]
    def _event(self,x,y,row): return SimpleNamespace(x=x,y=y,xdata=row.get('x_mm') if row else None,ydata=row.get('y_mm') if row else None,inaxes=True)
    def show_gestures(self,event=None):
        wx.MessageBox('Left drag uses the selected Orbit / Pan / Zoom mode.\n'
            'Wheel: zoom · middle drag: pan · Shift + left drag: pan in any mode.\n'
            'Probe: click an original sample; a drag never pins a sample.\n'
            'Double-click or F: fit · O/P/Z/I: mode · 1–5: camera presets · +/−: zoom.',
            'Viewport controls',wx.OK|wx.ICON_INFORMATION,self)

    def _key(self,event):
        if not self.window.HasFocus():event.Skip();return
        code=event.GetKeyCode();key=chr(code).lower() if 32<=code<127 else ''
        modes={'o':'Orbit','p':'Pan','z':'Zoom','i':'Probe'}
        if key in modes:self.set_mode(modes[key])
        elif key=='f' or code==wx.WXK_HOME:self.fit()
        elif key in ('+','='):self.zoom(.85)
        elif key=='-':self.zoom(1/.85)
        elif key in ('1','2','3','4','5'):self.set_camera(preset=['Isometric','Top','Bottom','Front','Right'][int(key)-1])
        else:event.Skip()

    def _on_press(self,obj,event):
        x,y=self.window.GetEventPosition();self._press=(x,y);self.window.SetFocus()
        # A temporary pan gesture must work even while inspecting samples.
        self._drag_mode='Pan' if self.window.GetShiftKey() else self.interaction
        if self._drag_mode=='Pan':self.style.OnMiddleButtonDown()
        elif self._drag_mode=='Zoom':self.style.OnRightButtonDown()
        elif self._drag_mode=='Orbit':self.style.OnLeftButtonDown()

    def _on_release(self,obj,event):
        x,y=self.window.GetEventPosition();mode=self._drag_mode or self.interaction
        if mode=='Pan':self.style.OnMiddleButtonUp()
        elif mode=='Zoom':self.style.OnRightButtonUp()
        elif mode=='Orbit':self.style.OnLeftButtonUp()
        elif self._press and math.hypot(x-self._press[0],y-self._press[1])<4:
            row=self._pick(x,y);self.callback(self.name,self._event(x,y,row),row,True)
        self._press=None;self._drag_mode=None

    def _on_move(self,obj,event):
        if self._press:
            if self._drag_mode != 'Probe':self.style.OnMouseMove()
            return
        if self.style.GetState()!=0:self.style.OnMouseMove();return
        if time.monotonic()-self._last_hover<.06:return
        self._last_hover=time.monotonic()
        x,y=self.window.GetEventPosition();row=self._pick(x,y);self.callback(self.name,self._event(x,y,row),row,False)
    def set_selection(self,row=None,*,pins=None,profile=None):
        self.selection=row
        if pins is not None: self.markers=pins
        if profile is not None: self.profile=profile
        self.render()
    def _markers(self):
        for row,color in [(v,(.25,.85,.8)) for v in self.markers]+([(self.selection,(1,.3,.4))] if self.selection else []):
            if self.name=='3D radiation' and row.get('kind')=='radiation': point=row['display_xyz']
            elif self.name=='3D fields' and row.get('kind')=='field': point=(row['x_mm'],row['y_mm'],row['z_mm'])
            else: continue
            sphere=vtk.vtkSphereSource(); sphere.SetCenter(*point); sphere.SetRadius(.5 if self.name!='3D radiation' else .025); sphere.Update(); self._actor(sphere.GetOutput(),color)
        if self.profile and self.name=='3D fields': self._line(self.profile[0],self.profile[1],(.25,.85,.8))
    def export_image(self):
        with wx.FileDialog(self,'Export scene',wildcard='PNG image (*.png)|*.png',style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal()!=wx.ID_OK: return
            capture=vtk.vtkWindowToImageFilter(); capture.SetInput(self.window.GetRenderWindow()); capture.Update(); writer=vtk.vtkPNGWriter(); writer.SetFileName(dialog.GetPath()); writer.SetInputConnection(capture.GetOutputPort()); writer.Write()
