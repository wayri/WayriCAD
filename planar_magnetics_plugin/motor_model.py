"""Inspectable sinusoidal machine/winding baseline; no inverter or rotor FEM.

Star-of-slots vector sums follow the conventional baseline reviewed in
https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/elp2.70002 section4.1.
The paper's optimized slot-shift/PM-reluctance geometries are not implemented.
"""
import cmath
import math

TAU=2*math.pi
REFERENCE='https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/elp2.70002'


def _real(x,name,minimum=None):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or (minimum is not None and x<minimum):raise ValueError(name+' must be finite'+(' and >= '+str(minimum) if minimum is not None else ''))
    return float(x)


def synthesize_winding(slots,poles,phases,coil_pitch_slots,turns_per_coil=1,style='distributed'):
    for value,name,lo,hi in ((slots,'slots',4,720),(poles,'poles',2,200),(phases,'phases',2,12),(coil_pitch_slots,'coil pitch',1,slots-1),(turns_per_coil,'turns',1,10000)):
        if isinstance(value,bool) or not isinstance(value,int) or not lo<=value<=hi:raise ValueError(name+' is outside its supported integer range')
    if poles%2:raise ValueError('Pole count must be even')
    if style not in ('distributed','concentrated','chorded'):raise ValueError('Unsupported winding style')
    if style=='distributed' and not math.isclose(coil_pitch_slots,slots/poles,abs_tol=1e-12):raise ValueError('Distributed baseline requires full-pitch coils; choose chorded or concentrated for shorter pitch')
    if style=='concentrated' and coil_pitch_slots!=1:raise ValueError('Concentrated tooth coils require pitch one slot')
    if style=='chorded' and coil_pitch_slots>=slots/poles:raise ValueError('Chorded pitch must be shorter than full pole pitch')
    # Odd phases use a symmetric full-cycle set. Even phases use independent
    # half-cycle axes (two-phase quadrature), avoiding duplicate +/- axes.
    # Common infinitesimal axis offset resolves exact phase-belt boundary
    # ties consistently for all slots, rather than favoring phase zero.
    target=[(TAU if phases%2 else math.pi)*j/phases+1e-7 for j in range(phases)]
    pp=poles//2;coils=[]
    for slot in range(slots):
        theta=TAU*pp*(slot+.5)/slots;end=theta+TAU*pp*coil_pitch_slots/slots
        vector=(cmath.exp(1j*theta)-cmath.exp(1j*end))/(2j)
        if abs(vector)<1e-12:raise ValueError('Coil pitch cancels fundamental flux')
        best=max(((round((sign*vector*cmath.exp(-1j*axis)).real,12),phase,sign) for phase,axis in enumerate(target) for sign in (1,-1)),key=lambda t:t[0])
        coils.append(dict(start_slot=slot+1,end_slot=(slot+coil_pitch_slots)%slots+1,phase=best[1],polarity=best[2],turns=turns_per_coil,top_layer=0,return_layer=1,theta_start_rad=theta,theta_end_rad=end))
    phase_data=[]
    for phase in range(phases):
        selected=[c for c in coils if c['phase']==phase]
        harmonics={}
        for harmonic in (1,3,5,7,9,11,13):
            total=sum(c['polarity']*(cmath.exp(1j*harmonic*c['theta_start_rad'])-cmath.exp(1j*harmonic*c['theta_end_rad']))/(2j) for c in selected)
            harmonics[str(harmonic)]=abs(total)/len(selected) if selected else 0.
            if harmonic==1:fundamental=total
        phase_data.append(dict(phase=phase,coil_count=len(selected),series_turns=len(selected)*turns_per_coil,axis_rad=cmath.phase(fundamental)%TAU if selected else 0.,kw=harmonics['1'],harmonic_kw=harmonics))
    counts=[p['coil_count'] for p in phase_data];magnitudes=[p['kw'] for p in phase_data]
    offsets=[cmath.exp(1j*(p['axis_rad']-target[p['phase']])) for p in phase_data]
    balance=max(counts)==min(counts) and min(counts)>0 and max(magnitudes)-min(magnitudes)<1e-9 and max(abs(v-offsets[0]) for v in offsets)<1e-8
    tensor=[[sum(math.cos(p['axis_rad'])**2 for p in phase_data),sum(math.cos(p['axis_rad'])*math.sin(p['axis_rad']) for p in phase_data)],
            [sum(math.cos(p['axis_rad'])*math.sin(p['axis_rad']) for p in phase_data),sum(math.sin(p['axis_rad'])**2 for p in phase_data)]]
    tensor_error=max(abs(tensor[i][j]-(phases/2 if i==j else 0.)) for i in range(2) for j in range(2))
    balance=balance and tensor_error<1e-8
    return dict(phase_topology='symmetric full-cycle phases' if phases%2 else 'independent H-bridge half-cycle phases',phase_axis_tensor=tensor,phase_axis_tensor_error=tensor_error,schema='wayricad.motor-winding/v1',status='BALANCED' if balance else 'UNBALANCED',slots=slots,poles=poles,phases=phases,coil_pitch_slots=coil_pitch_slots,style=style,coils=coils,phase_data=phase_data,
        assumptions=['Two-layer uniform-slot coils, all coils in each phase series connected; no conductor packing/end-turn geometry.',
                     'Even phase counts use independent half-cycle phase axes, requiring independent phase drives; not a conventional common-neutral multiphase connection.',
                     'Winding harmonics are geometry factors, not predicted torque ripple or cogging.'],references=[REFERENCE])


def pm_airgap_fundamental(*,remanence_t,magnet_thickness_mm,gap_mm,recoil_mu_r=1.05,pole_arc_fraction=1.):
    br=_real(remanence_t,'Remanence',1e-12);lm=_real(magnet_thickness_mm,'Magnet thickness',1e-12);gap=_real(gap_mm,'Air gap',1e-12);mu=_real(recoil_mu_r,'Recoil permeability',1)
    arc=_real(pole_arc_fraction,'Pole arc fraction',1e-12)
    if arc>1:raise ValueError('Pole arc fraction must be <=1')
    plateau=br*lm/(lm+mu*gap)
    return dict(fundamental_b_t=4/math.pi*plateau*math.sin(math.pi*arc/2),plateau_b_t=plateau,
        assumptions=['Equal magnet/gap area, infinite-permeability iron, no leakage/fringing/saturation; explicit recoil permeability.',
                     'Alternating rectangular pole flux converted to sinusoidal fundamental; harmonic flux is not included in motor dynamics.'])


def build_motor(winding,*,kind='rotary',fundamental_b_t,active_length_mm,airgap_radius_mm=None,pole_pitch_mm=None,excitation='permanent_magnet'):
    if winding.get('status')!='BALANCED':raise ValueError('Winding is unbalanced; inspect coil table before simulating')
    if kind not in ('rotary','linear'):raise ValueError('Motor kind must be rotary or linear')
    if excitation not in ('permanent_magnet','wound_field'):raise ValueError('Choose permanent_magnet or wound_field excitation')
    b=_real(fundamental_b_t,'Fundamental air-gap B',1e-12);length=_real(active_length_mm,'Active length',1e-12)*.001
    pp=winding['poles']//2
    if kind=='rotary':
        radius=_real(airgap_radius_mm,'Air-gap radius',1e-12)*.001;scale=float(pp);flux=2*b*length*radius/pp
    else:
        pitch=_real(pole_pitch_mm,'Pole pitch',1e-12)*.001;scale=math.pi/pitch;flux=2*b*length*pitch/math.pi
    phase=[dict(p,flux_linkage_peak_Wb=p['series_turns']*p['kw']*flux) for p in winding['phase_data']]
    return dict(schema='wayricad.sinusoidal-motor/v1',kind=kind,excitation=excitation,phase_data=phase,electrical_radians_per_mechanical_unit=scale,
        fundamental_b_t=b,active_length_mm=active_length_mm,airgap_radius_mm=airgap_radius_mm,pole_pitch_mm=pole_pitch_mm,winding=winding,
        assumptions=['Sinusoidal fundamental flux linkage derived from supplied air-gap B and active geometry; no fixed assumed Ke.',
                     'Nonsalient synchronous machine: no reluctance torque, slotting, saturation, iron losses, end effects or winding R/L voltage dynamics.',
                     'Wound-field mode requires independently supplied fundamental B; field current/rotor excitation circuit is not solved.',
                     'Linear mode is a periodic travelling-field baseline, not a finite-stroke/end-effect field solver.'])


def evaluate(model,position,speed,currents):
    position=_real(position,'Position');speed=_real(speed,'Speed')
    if len(currents)!=len(model['phase_data']):raise ValueError('Supply one current per phase')
    currents=[_real(i,'Phase current') for i in currents];scale=model['electrical_radians_per_mechanical_unit']
    flux=[];derivative=[]
    for phase in model['phase_data']:
        angle=scale*position-phase['axis_rad'];peak=phase['flux_linkage_peak_Wb']
        flux.append(peak*math.cos(angle));derivative.append(-scale*peak*math.sin(angle))
    effort=sum(i*d for i,d in zip(currents,derivative));emf=[d*speed for d in derivative]
    return dict(flux_linkage_Wb=flux,back_emf_V=emf,**({'torque_Nm':effort} if model['kind']=='rotary' else {'force_N':effort}),
                mechanical_power_W=effort*speed,electromagnetic_power_W=sum(e*i for e,i in zip(emf,currents)))


def phase_events(model,speed):
    speed=_real(speed,'Speed');scale=model['electrical_radians_per_mechanical_unit'];rows=[]
    if speed==0:return dict(status='UNKNOWN_AT_STANDSTILL',events=[],electrical_period_s=None,limitation='No back EMF or time-based crossings at zero speed; position sensing/startup control required.')
    direction=1 if speed>0 else -1
    for phase in model['phase_data']:
        for offset,name in ((0.,'EMF zero (negative-going)'),(math.pi,'EMF zero (positive-going)'),(math.pi/2,'Negative EMF peak' if direction>0 else 'Positive EMF peak'),(3*math.pi/2,'Positive EMF peak' if direction>0 else 'Negative EMF peak')):
            angle=(phase['axis_rad']+offset)%TAU;travel=(direction*angle)%TAU;position=direction*travel/scale
            rows.append(dict(phase=phase['phase'],event=name,electrical_angle_deg=math.degrees(angle),mechanical_position=position,time_s=travel/(scale*abs(speed))))
    return dict(status='CONSTANT_SPEED_REFERENCE',events=sorted(rows,key=lambda r:r['time_s']),electrical_period_s=TAU/(scale*abs(speed)),limitation='Constant signed speed reference from position zero; phase timing only, not inverter switching/PWM/dead-time instructions.')


def simulate_motion(model,*,peak_current,inertia_or_mass,damping=0.,load=0.,duration=.1,dt=.0001,initial_position=0.,initial_speed=0.):
    current=_real(peak_current,'Peak current');mass=_real(inertia_or_mass,'Inertia/mass',1e-15);damping=_real(damping,'Damping',0);load=_real(load,'Opposing load');duration=_real(duration,'Duration',1e-12);dt=_real(dt,'Time step',1e-12)
    ratio=duration/dt
    if not math.isfinite(ratio) or ratio>20000:raise ValueError('Simulation exceeds 20,000 time steps')
    steps=math.ceil(ratio)
    if steps>20000:raise ValueError('Simulation exceeds 20,000 time steps')
    h=duration/steps;position=_real(initial_position,'Initial position');speed=_real(initial_speed,'Initial speed');rows=[];scale=model['electrical_radians_per_mechanical_unit']
    def operating(q,v):
        currents=[-current*math.sin(scale*q-p['axis_rad']) for p in model['phase_data']]
        return evaluate(model,q,v,currents),currents
    def rate(q,v):
        r,_=operating(q,v);effort=r.get('torque_Nm',r.get('force_N'))
        return v,(effort-damping*v-load)/mass
    for step in range(steps+1):
        result,currents=operating(position,speed)
        rows.append(dict(time_s=step*h,position=position,speed=speed,phase_current_A=currents,**result))
        if step==steps:break
        a=rate(position,speed);b=rate(position+h*a[0]/2,speed+h*a[1]/2);c=rate(position+h*b[0]/2,speed+h*b[1]/2);d=rate(position+h*c[0],speed+h*c[1])
        position+=h*(a[0]+2*b[0]+2*c[0]+d[0])/6;speed+=h*(a[1]+2*b[1]+2*c[1]+d[1])/6
        if not math.isfinite(position+speed):raise ValueError('Mechanics integration became nonfinite; reduce dt or inspect inputs')
    return dict(samples=rows,dt_s=h,limitation='Ideal position-synchronous quadrature phase-current drive, unlimited voltage/compliance. No inverter/current-loop/startup synchronisation model; load is constant signed opposing effort.')


def simulate_motion_spice(model,*,peak_current,inertia_or_mass,damping=0.,load=0.,duration=.1,dt=.0001,initial_position=0.,initial_speed=0.):
    """KiCad ngspice mechanics for balanced ideal quadrature-current excitation.

    The balanced sinusoidal phase model has constant electromagnetic effort.
    Its mechanical analogue is solved by ngspice; phase flux/EMF are evaluated
    at the resulting position. This is not an inverter or winding-circuit solve.
    """
    from wayricad_runtime.spice_backend import simulate
    current=_real(peak_current,'Peak current');mass=_real(inertia_or_mass,'Inertia/mass',1e-15);damping=_real(damping,'Damping',0);load=_real(load,'Signed opposing load');duration=_real(duration,'Duration',1e-12);dt=_real(dt,'Time step',1e-12)
    q0=_real(initial_position,'Initial position');v0=_real(initial_speed,'Initial speed');scale=model['electrical_radians_per_mechanical_unit']
    phase=model['phase_data'];weights=[p['flux_linkage_peak_Wb'] for p in phase]
    oscillatory=sum(w*cmath.exp(2j*p['axis_rad']) for w,p in zip(weights,phase))
    if abs(oscillatory)>1e-8*sum(weights):raise ValueError('Constant-effort SPICE mechanics requires balanced sinusoidal phase axes and linkage')
    effort=current*scale*sum(weights)/2
    deck=['WayriCAD ideal current-driven synchronous mechanics',f'Idrive 0 speed {effort-load:.15g}',f'Cmass speed 0 {mass:.15g} IC={v0:.15g}',
          'Gposition 0 position speed 0 1',f'Cposition position 0 1 IC={q0:.15g}']
    if damping:deck.append(f'Rdamping speed 0 {1/damping:.15g}')
    deck.append('.end');netlist='\n'.join(deck)+'\n'
    result=simulate(netlist,analysis='tran',vectors=['time','v(speed)','v(position)'],time_step_s=dt,duration_s=duration)
    vectors=result['vectors'];rows=[]
    for time,q,v in zip(vectors['time']['real'],vectors['v(position)']['real'],vectors['v(speed)']['real']):
        currents=[-current*math.sin(scale*q-p['axis_rad']) for p in phase]
        rows.append(dict(time_s=time,position=q,speed=v,phase_current_A=currents,**evaluate(model,q,v,currents)))
    return dict(samples=rows,dt_s=dt,engine=result['engine'],engine_version=result['version'],engine_path=result['path'],engine_log=result['log'],netlist=netlist,
                limitation='KiCad ngspice transient solves constant ideal-quadrature electromagnetic effort with inertia/mass and viscous damping. Position is a SPICE integrator. No winding voltage dynamics, inverter or current controller is simulated.')
