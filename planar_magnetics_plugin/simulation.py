"""Generated magnetic equivalents simulated by KiCad's isolated ngspice engine."""
import cmath
import math
from .equivalent import spice, _positive


def run_simulation(model, *, voltage_v=1., load_ohm=10., start_hz=10., stop_hz=1e6):
    from wayricad_runtime.spice_backend import simulate
    mechanical=model.get('actuator');transformer='secondary_L_H' in model
    voltage=_positive(voltage_v,'Drive voltage');load=_positive(load_ohm,'Secondary load') if transformer else 10.
    prefix='WayriCAD reviewed magnetic equivalent\n'+spice(model)
    if mechanical:
        deck=prefix+f'Vdrive p 0 {voltage:.12g}\nXdevice p 0 speed WayriCADMagnetic\n.end\n'
        engine=simulate(deck,analysis='op',vectors=['speed','vdrive#branch'])
        speed=float(engine['vectors']['speed']['real'][0]);current=-float(engine['vectors']['vdrive#branch']['real'][0])
        effort=mechanical['Bl_N_per_A']*current
        return {'schema':'wayricad.magnetic-simulation/v1','analysis':'DC operating point','engine':engine,
                'drive_voltage_V':voltage,'current_A':current,'speed':speed,
                'speed_unit':'rad/s' if mechanical['motion_type']=='rotary' else 'm/s',
                'effort':effort,'effort_unit':'N m' if mechanical['motion_type']=='rotary' else 'N',
                'electrical_input_W':voltage*current,'converted_mechanical_W':effort*speed,
                'netlist':deck,'limits':'Steady state of explicit linear mechanics. A spring can make final speed zero. No transient, commutation or saturation simulation.'}
    start=_positive(start_hz,'Start frequency');stop=_positive(stop_hz,'Stop frequency')
    if not start<stop or stop>1e9 or start<1e-3:raise ValueError('AC sweep requires 0.001 Hz <= start < stop <= 1 GHz.')
    deck=prefix+f'Vdrive p 0 DC 0 AC {voltage:.12g}\n'
    if transformer:deck+=f'Xdevice p 0 secondary 0 WayriCADMagnetic\nRload secondary 0 {load:.12g}\n'
    else:deck+='Xdevice p 0 WayriCADMagnetic\n'
    deck+='.end\n'
    vectors=['frequency','p','vdrive#branch']+(['secondary'] if transformer else [])
    engine=simulate(deck,analysis='ac',vectors=vectors,frequency_hz=start,frequency_stop_hz=stop,points_per_decade=10)
    def complex_values(name):
        vector=engine['vectors'][name]
        return [complex(a,b) for a,b in zip(vector['real'],vector['imag'])]
    freq=engine['vectors']['frequency']['real'];vp=complex_values('p');source=complex_values('vdrive#branch');rows=[]
    output=complex_values('secondary') if transformer else [None]*len(freq)
    for f,v,i,out in zip(freq,vp,source,output):
        i=-i
        if abs(i)<1e-30:raise ValueError('Source current is too small to evaluate input impedance reliably.')
        z=v/i
        row={'frequency_Hz':float(f),'input_impedance_magnitude_ohm':abs(z),'input_impedance_phase_deg':math.degrees(cmath.phase(z)),
             'input_impedance_real_ohm':z.real,'input_impedance_imag_ohm':z.imag,'input_current_magnitude_A':abs(i)}
        if out is not None:row.update(output_voltage_magnitude_V=abs(out),voltage_gain_magnitude=abs(out/v),voltage_gain_phase_deg=math.degrees(cmath.phase(out/v)))
        rows.append(row)
    if not rows:raise ValueError('KiCad ngspice returned no AC samples.')
    return {'schema':'wayricad.magnetic-simulation/v1','analysis':'Small-signal AC sweep','engine':engine,
            'drive_voltage_V':voltage,'secondary_load_ohm':load if transformer else None,'samples':rows,'netlist':deck,
            'limits':('Only one frequency returned for this narrow interval; widen the sweep to obtain a curve. ' if len(rows)==1 else '')+'Constant incremental L and DC winding resistance; only explicit C included. No frequency-dependent core loss, eddy currents or nonlinear saturation. AC magnitudes use the source phasor convention.'}
