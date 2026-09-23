"""Native guided winding/EMF/mechanics review; generated geometry, no PCB writes."""
import hashlib
import csv
import html
import json
import math
from pathlib import Path
import threading
import uuid
import wx
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon
from .plot_canvas import FigureCanvasWxAgg
from .motor_model import synthesize_winding,build_motor,pm_airgap_fundamental,evaluate,phase_events,simulate_motion_spice
from .motor_layout import annular_coil_paths


class MotorDialog(wx.Dialog):
    def __init__(self,parent,board_path):
        super().__init__(parent,title='Motor winding studio · model, review, simulate',size=(1180,800),style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        self.SetIcon(wx.Icon(str(Path(__file__).with_name('resources')/'icon-48.png'),wx.BITMAP_TYPE_PNG))
        self.SetSize(self.FromDIP((1120,800)));self.SetMinSize(self.FromDIP((980,650)))
        self.board_path=Path(board_path);self.source_hash=self._hash();self.model=None;self.simulation=None;self.review=None;self.layout_paths=None;self.generation=0;self.fields={};self.busy=False
        root=wx.BoxSizer(wx.VERTICAL)
        note=wx.StaticText(self,label='1 Configure a winding   →   2 Review layout and EMF   →   3 Simulate with KiCad SPICE\nGenerated two-layer coil layout and sinusoidal machine model; no PCB copper is changed.')
        root.Add(note,0,wx.ALL,10)
        body=wx.BoxSizer(wx.HORIZONTAL);settings=wx.Notebook(self,size=self.FromDIP((330,-1)));self.settings=settings;body.Add(settings,0,wx.EXPAND|wx.ALL,6)
        self.setting_pages={}
        for title in ('Winding','Field','Drive'):
            panel=wx.ScrolledWindow(settings,style=wx.VSCROLL);panel.SetScrollRate(0,self.FromDIP(12))
            box=wx.BoxSizer(wx.VERTICAL);panel.SetSizer(box);settings.AddPage(panel,title);self.setting_pages[title]=(panel,box)
        def choice(page,key,label,items):
            panel,box=self.setting_pages[page];box.Add(wx.StaticText(panel,label=label),0,wx.TOP|wx.LEFT,8);ctrl=wx.Choice(panel,choices=items);ctrl.SetSelection(0);box.Add(ctrl,0,wx.EXPAND|wx.ALL,7);self.fields[key]=ctrl;ctrl.Bind(wx.EVT_CHOICE,self.invalidate);return ctrl
        def value(page,key,label,text):
            panel,box=self.setting_pages[page];row=wx.BoxSizer(wx.HORIZONTAL);row.Add(wx.StaticText(panel,label=label),1,wx.ALIGN_CENTER_VERTICAL);ctrl=wx.TextCtrl(panel,value=text,size=self.FromDIP((90,-1)));row.Add(ctrl);box.Add(row,0,wx.EXPAND|wx.ALL,7);self.fields[key]=ctrl;ctrl.Bind(wx.EVT_TEXT,self.invalidate)
        self.preset=choice('Winding','preset','Balanced presets',['36 slots / 4 poles / 3 phases']+[f'{m} phases · {4*m} slots / 2 poles' for m in range(2,13)])
        self.preset.Unbind(wx.EVT_CHOICE);self.preset.Bind(wx.EVT_CHOICE,self.preset_changed)
        for key,label,text in [('slots','Slots','36'),('poles','Poles','4'),('phases','Phases','3'),('coil_pitch_slots','Coil pitch (slots)','9'),('turns_per_coil','Turns per coil','10')]:value('Winding',key,label,text)
        choice('Winding','style','Coil style',['distributed','concentrated','chorded'])
        for key,label,text in [('preview_inner_radius_mm','Preview inner radius (mm)','10'),('preview_outer_radius_mm','Preview outer radius (mm)','35')]:value('Winding',key,label,text)
        panel,box=self.setting_pages['Winding'];warning=wx.StaticText(panel,label='Annular view is a phase/slot projection only. It does not generate PCB copper or check trace packing.');warning.Wrap(self.FromDIP(295));box.Add(warning,0,wx.ALL,8)
        choice('Field','kind','Machine',['Rotary PMSM','Linear synchronous','Rotary wound-field'])
        choice('Field','flux_source','Air-gap field input',['Supplied fundamental B','Simple PM magnet / gap estimate'])
        for key,label,text in [('fundamental_b_t','Fundamental B (T)','0.5'),('active_length_mm','Active length (mm)','50'),('airgap_radius_mm','Rotary radius (mm)','20'),('pole_pitch_mm','Linear pole pitch (mm)','30'),('remanence_t','Magnet Br (T)','1.2'),('magnet_thickness_mm','Magnet thickness (mm)','3'),('gap_mm','Air gap (mm)','1')]:value('Field',key,label,text)
        for key,label,text in [('preview_speed','EMF speed (rad/s or m/s)','10'),('peak_current','Peak phase current (A)','2'),('inertia_or_mass','Inertia (kg m²) / mass (kg)','0.01'),('damping','Viscous damping (SI)','0.02'),('load','Signed load (N m / N)','0'),('duration','Duration (s)','0.2'),('dt','Maximum step (s)','0.0001')]:value('Drive',key,label,text)
        panel,box=self.setting_pages['Drive'];text=wx.StaticText(panel,label='Ideal position-synchronous currents. SPICE solves inertia/mass and damping; this is not an inverter or voltage-driven winding simulation.');text.Wrap(self.FromDIP(295));box.Add(text,0,wx.ALL,8)
        for panel,_box in self.setting_pages.values():panel.FitInside()
        self.tabs=wx.Notebook(self);body.Add(self.tabs,1,wx.EXPAND|wx.ALL,6);self.figures={};self.canvases={}
        for title in ('Layout','EMF and effort','Mechanics'):
            panel=wx.Panel(self.tabs);sizer=wx.BoxSizer(wx.VERTICAL)
            if title=='Layout':
                row=wx.BoxSizer(wx.HORIZONTAL);row.Add(wx.StaticText(panel,label='Show winding phase'),0,wx.ALIGN_CENTER_VERTICAL|wx.RIGHT,8)
                self.phase_view=wx.Choice(panel,choices=['All phases']);self.phase_view.SetSelection(0);self.phase_view.Bind(wx.EVT_CHOICE,self.on_phase_view)
                row.Add(self.phase_view,0,wx.RIGHT,12);row.Add(wx.StaticText(panel,label='Phase lanes and coil outlines are logical, not routed copper.'),0,wx.ALIGN_CENTER_VERTICAL)
                sizer.Add(row,0,wx.EXPAND|wx.ALL,8)
            figure=Figure(figsize=(7,5),layout='constrained');canvas=FigureCanvasWxAgg(panel,-1,figure);sizer.Add(canvas,1,wx.EXPAND);panel.SetSizer(sizer);self.tabs.AddPage(panel,title);self.figures[title]=figure;self.canvases[title]=canvas
        self.timing=wx.ListCtrl(self.tabs,style=wx.LC_REPORT)
        for label,width in [('Phase',65),('Reference event',210),('Electrical °',105),('Position (rad / m)',120),('Time (s)',105)]:self.timing.InsertColumn(self.timing.GetColumnCount(),label,width=self.FromDIP(width))
        self.tabs.AddPage(self.timing,'Phase timing');self.details=wx.TextCtrl(self.tabs,style=wx.TE_MULTILINE|wx.TE_READONLY);self.tabs.AddPage(self.details,'Model evidence')
        root.Add(body,1,wx.EXPAND)
        self.status=wx.StaticText(self,label='Configure the winding and select Review.');root.Add(self.status,0,wx.EXPAND|wx.ALL,8)
        actions=wx.BoxSizer(wx.HORIZONTAL)
        self.review_button=wx.Button(self,label='Review winding');self.sim_button=wx.Button(self,label='Run KiCad SPICE');self.export_button=wx.Button(self,label='Export reviewed report')
        for button,handler in ((self.review_button,self.on_review),(self.sim_button,self.on_simulate),(self.export_button,self.on_export)):
            actions.Add(button,0,wx.ALL,6);button.Bind(wx.EVT_BUTTON,handler)
        root.Add(actions,0,wx.ALIGN_RIGHT);self.SetSizer(root);self.invalidate();self.Bind(wx.EVT_CLOSE,self.close)
    def _hash(self):return hashlib.sha256(self.board_path.read_bytes()).hexdigest() if self.board_path.is_file() else None
    def close(self,event):
        self.generation+=1
        if self.IsModal():self.EndModal(wx.ID_CANCEL)
        else:self.Destroy()
    def number(self,key):return float(self.fields[key].GetValue())
    def text(self,key):return self.fields[key].GetStringSelection()
    def invalidate(self,event=None):
        self.generation+=1;self.model=None;self.review=None;self.layout_paths=None;self.simulation=None;self.sim_button.Enable(False);self.export_button.Enable(False)
        self.status.SetLabel('Inputs changed · review the winding before simulation or export.');self.timing.DeleteAllItems();self.details.SetValue('')
        for title,figure in self.figures.items():
            figure.clear();axis=figure.add_subplot();axis.axis('off');axis.text(.5,.5,'Review the winding to see '+title.lower(),ha='center',va='center',transform=axis.transAxes);self.canvases[title].draw()
        wound=self.text('kind')=='Rotary wound-field'
        if wound:self.fields['flux_source'].SetSelection(0)
        self.fields['flux_source'].Enable(not wound)
        pm=self.text('flux_source').startswith('Simple');linear=self.text('kind').startswith('Linear')
        self.fields['fundamental_b_t'].Enable(not pm)
        for key in ('remanence_t','magnet_thickness_mm','gap_mm'):self.fields[key].Enable(pm)
        self.fields['airgap_radius_mm'].Enable(not linear);self.fields['pole_pitch_mm'].Enable(linear)
        for key in ('preview_inner_radius_mm','preview_outer_radius_mm'):self.fields[key].Enable(not linear)
        if event:event.Skip()
    def preset_changed(self,event):
        index=self.preset.GetSelection();m=3 if index==0 else index+1
        for key,value in dict(slots=36 if index==0 else 4*m,poles=4 if index==0 else 2,phases=m,coil_pitch_slots=9 if index==0 else 2*m).items():self.fields[key].ChangeValue(str(value))
        self.fields['style'].SetSelection(0);self.invalidate()
    def on_review(self,event=None):
        try:self.build_review()
        except Exception as exc:self.invalidate();self.status.SetLabel(str(exc))
    def build_review(self):
        self.invalidate();self.source_hash=self._hash()
        values={key:self.number(key) for key in ('slots','poles','phases','coil_pitch_slots','turns_per_coil')}
        if any(v!=int(v) for v in values.values()):raise ValueError('Winding counts must be integers.')
        winding=synthesize_winding(**{k:int(v) for k,v in values.items()},style=self.text('style'))
        if winding['status']!='BALANCED':raise ValueError('Unbalanced winding: change slots, phases or pitch. No balanced-machine result is available.')
        flux=None;b=None
        if self.text('flux_source').startswith('Simple'):
            if self.text('kind')=='Rotary wound-field':raise ValueError('Wound-field mode requires supplied fundamental B.')
            flux=pm_airgap_fundamental(**{k:self.number(k) for k in ('remanence_t','magnet_thickness_mm','gap_mm')});b=flux['fundamental_b_t']
        else:b=self.number('fundamental_b_t')
        kind='linear' if self.text('kind').startswith('Linear') else 'rotary'
        layout_paths=annular_coil_paths(winding,self.number('preview_inner_radius_mm'),self.number('preview_outer_radius_mm')) if kind=='rotary' else None
        model=build_motor(winding,kind=kind,fundamental_b_t=b,active_length_mm=self.number('active_length_mm'),airgap_radius_mm=self.number('airgap_radius_mm') if kind=='rotary' else None,pole_pitch_mm=self.number('pole_pitch_mm') if kind=='linear' else None,excitation='wound_field' if self.text('kind')=='Rotary wound-field' else 'permanent_magnet')
        speed=self.number('preview_speed');peak=self.number('peak_current');timing=phase_events(model,speed);wave=[]
        for index in range(181):
            angle=2*math.pi*index/180;position=angle/model['electrical_radians_per_mechanical_unit'];currents=[-peak*math.sin(angle-p['axis_rad']) for p in model['phase_data']]
            wave.append(dict(electrical_angle_deg=math.degrees(angle),**evaluate(model,position,speed,currents)))
        self.model=model;self.layout_paths=layout_paths
        self.phase_view.SetItems(['All phases']+[f"Phase {chr(65+phase)}" for phase in range(winding['phases'])]);self.phase_view.SetSelection(0)
        self.review=dict(model=model,flux_estimate=flux,timing=timing,waveforms=wave,inputs={key:(control.GetStringSelection() if isinstance(control,wx.Choice) else control.GetValue()) for key,control in self.fields.items()},source_board=str(self.board_path),source_sha256=self.source_hash,
            layout_note='Annular phase/slot projection; radial phase lanes are for visual separation only, not a copper pattern, spacing check, or manufacturable layout.' if kind=='rotary' else 'Linear logical coil connections; not manufactured geometry.')
        self.draw_review();self.sim_button.Enable(True);self.export_button.Enable(True)
        self.status.SetLabel(f"Balanced · {winding['phase_topology']} · kw {winding['phase_data'][0]['kw']:.5f} · B₁ {b:.4g} T. Timing is a reference, not PWM.")
        return self.review
    def on_phase_view(self,event):
        if self.model:self.draw_layout()
        event.Skip()

    def draw_layout(self):
        model=self.model;w=model['winding'];fig=self.figures['Layout'];fig.clear();ax=fig.add_subplot()
        colors=['#0072b2','#d55e00','#009e73','#cc79a7','#e69f00','#56b4e9','#725a9b','#a74747','#658144','#477777','#aa8855','#555555']
        selected=self.phase_view.GetSelection()-1
        if model['kind']=='linear':
            for coil in w['coils']:
                if selected>=0 and coil['phase']!=selected:continue
                color=colors[coil['phase']%len(colors)]
                ax.plot([coil['start_slot'],coil['end_slot']],[1,0],color=color,alpha=.65,lw=1.2)
                ax.text(coil['start_slot'],1.06,str(coil['start_slot']),ha='center',fontsize=8)
            ax.set_ylim(-.2,1.3)
            ax.set_title('Linear logical coil connections · not copper geometry',fontsize=12)
        else:
            inner=self.number('preview_inner_radius_mm');outer=self.number('preview_outer_radius_mm')
            ax.add_patch(Circle((0,0),inner,fill=False,edgecolor='#667986',lw=1.2,ls='--'))
            ax.add_patch(Circle((0,0),outer,fill=False,edgecolor='#667986',lw=1.2,ls='--'))
            for coil in self.layout_paths:
                if selected>=0 and coil['phase']!=selected:continue
                phase=coil['phase'];color=colors[phase%len(colors)]
                ax.add_patch(Polygon(coil['points_mm'],closed=True,facecolor=color,
                                     edgecolor=color,alpha=.25 if selected<0 else .55,lw=.8 if selected<0 else 1.4))
                if selected>=0:
                    x,y=coil['start_mm'];ax.plot(x,y,'o',color=color,markersize=4)
                    label=f"{chr(65+phase)}{'+' if coil['polarity']>0 else '−'} {coil['start_slot']}→{coil['end_slot']}"
                    ax.annotate(label,(x,y),xytext=(3,3),textcoords='offset points',fontsize=6,color=color)
            ax.set_aspect('equal');ax.set_xlim(-outer*1.2,outer*1.2);ax.set_ylim(-outer*1.2,outer*1.2)
            ax.set_title(f"Annular phase/slot projection · ID {2*inner:g} mm · OD {2*outer:g} mm\nLogical phase lanes, not routed copper or checked spacing",fontsize=11)
        for phase in w['phase_data']:
            if selected<0 or phase['phase']==selected:
                name=chr(65+phase['phase']);count=phase['coil_count']
                ax.plot([],[],color=colors[phase['phase']%len(colors)],lw=3,label=f"Phase {name} · {count} coils · kw {phase['kw']:.3f}")
        ax.axis('off');ax.legend(loc='upper left',bbox_to_anchor=(1.,1.),fontsize=8);self.canvases['Layout'].draw()

    def draw_review(self):
        model=self.model;w=model['winding'];self.draw_layout()
        fig=self.figures['EMF and effort'];fig.clear();a,b=fig.subplots(2,1);wave=self.review['waveforms'];x=[r['electrical_angle_deg'] for r in wave]
        for phase in range(w['phases']):a.plot(x,[r['back_emf_V'][phase] for r in wave],label=str(phase+1))
        a.set_ylabel('Phase back EMF (V)');a.legend(title='Phase',ncol=min(6,w['phases']),fontsize=8);a.grid(alpha=.2)
        key='torque_Nm' if model['kind']=='rotary' else 'force_N';effort=[r[key] for r in wave];b.plot(x,effort);b.set_ylabel('Torque (N m)' if model['kind']=='rotary' else 'Force (N)');b.set_xlabel('Electrical position (°)');b.grid(alpha=.2)
        if max(effort)-min(effort)<1e-8*max(1.,max(abs(v) for v in effort)):
            margin=max(1e-6,max(abs(v) for v in effort)*.1);b.set_ylim(min(effort)-margin,max(effort)+margin)
        b.ticklabel_format(axis='y',style='plain',useOffset=False);self.canvases['EMF and effort'].draw()
        self.timing.DeleteAllItems()
        for row in self.review['timing']['events']:
            i=self.timing.InsertItem(self.timing.GetItemCount(),str(row['phase']+1))
            for col,value in enumerate((row['event'],f"{row['electrical_angle_deg']:.3f}",f"{row['mechanical_position']:.6g}",f"{row['time_s']:.6g}"),1):self.timing.SetItem(i,col,value)
        self.details.SetValue(json.dumps(self.review,indent=2,allow_nan=False))
    def on_simulate(self,event=None):
        if not self.model or self.busy:return
        try:args={k:self.number(k) for k in ('peak_current','inertia_or_mass','damping','load','duration','dt')}
        except ValueError as exc:self.status.SetLabel(str(exc));return
        model=self.model;generation=self.generation;self.busy=True;self.sim_button.Enable(False);self.review_button.Disable();self.export_button.Disable();self.settings.Disable();self.status.SetLabel('KiCad SPICE is solving the ideal-current mechanical model…')
        def worker():
            try:result=simulate_motion_spice(model,**args);error=None
            except Exception as exc:result=None;error=str(exc)
            wx.CallAfter(self.finish_simulation,generation,result,error)
        threading.Thread(target=worker,daemon=True).start()
    def finish_simulation(self,generation,result,error):
        if not self:return
        self.busy=False
        self.settings.Enable();self.review_button.Enable();self.export_button.Enable(bool(self.review))
        if generation!=self.generation:return
        self.sim_button.Enable(True)
        if error:self.status.SetLabel(error);return
        self.simulation=result;fig=self.figures['Mechanics'];fig.clear();a,b=fig.subplots(2,1);rows=result['samples'];t=[r['time_s'] for r in rows]
        a.plot(t,[r['position'] for r in rows]);a.set_ylabel('Position (rad)' if self.model['kind']=='rotary' else 'Position (m)')
        b.plot(t,[r['speed'] for r in rows]);b.set_ylabel('Speed (rad/s)' if self.model['kind']=='rotary' else 'Speed (m/s)');b.set_xlabel('Time (s)')
        for axis in (a,b):axis.grid(alpha=.2)
        self.canvases['Mechanics'].draw();self.tabs.SetSelection(2);self.status.SetLabel(f"{result['engine_version']} · {len(rows)} samples · ideal quadrature-current mechanics, not inverter switching.");self.status.SetToolTip(result['engine_path'])
    def export_review(self):
        if not self.review:raise ValueError('Review current inputs before exporting.')
        if self.source_hash is None or self._hash()!=self.source_hash:raise ValueError('Saved board changed or is unavailable; review again before export.')
        base=self.board_path.parent/'reports'/'wayricad-magnetics'
        if not base.resolve().is_relative_to(self.board_path.parent.resolve()):raise ValueError('Report directory is redirected outside the project.')
        folder=base/('motor-'+uuid.uuid4().hex[:12]);folder.mkdir(parents=True)
        payload=dict(self.review,simulation=self.simulation);text=json.dumps(payload,indent=2,allow_nan=False);(folder/'model.json').write_text(text,encoding='utf-8')
        with (folder/'coils.csv').open('w',newline='',encoding='utf-8') as stream:
            keys=['start_slot','end_slot','phase','polarity','turns','top_layer','return_layer'];writer=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(self.model['winding']['coils'])
        for name,fig in self.figures.items():fig.savefig(folder/(name.replace(' ','-')+'.svg'))
        if self.simulation:(folder/'mechanics.cir').write_text(self.simulation['netlist'],encoding='utf-8')
        images=''.join('<h2>'+html.escape(name)+'</h2><img style="max-width:100%" src="'+name.replace(' ','-')+'.svg">' for name in self.figures)
        body='<!doctype html><meta charset="utf-8"><title>Motor winding review</title><style>body{font:15px system-ui;max-width:1050px;margin:30px auto}pre{white-space:pre-wrap}</style><h1>Motor winding review</h1><p>Generated logical layout, sinusoidal flux and ideal-current mechanics. No inverter or rotor field solve.</p>'+images+'<h2>Inputs, evidence and limitations</h2><pre>'+html.escape(text)+'</pre>'
        (folder/'report.html').write_text(body,encoding='utf-8');return folder
    def on_export(self,event=None):
        try:self.status.SetLabel('Exported '+str(self.export_review()))
        except Exception as exc:self.status.SetLabel(str(exc))

