"""Planar winding geometry and reduced-order electrical/magnetic models."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path


MU0 = 4e-7 * math.pi
EPS0 = 8.8541878128e-12
COPPER_RHO = 1.724e-8
BOLTZMANN = 1.380649e-23


@dataclass(frozen=True)
class MagneticCore:
    name: str
    family: str
    material: str
    permeability: float
    effective_area_mm2: float
    path_length_mm: float
    gap_mm: float
    saturation_t: float
    loss_k: float = 0.0
    loss_alpha: float = 1.5
    loss_beta: float = 2.5


CORE_CATALOG = {
    core.name: core for core in (
        MagneticCore("Air / no core", "Air", "Air", 1.0, 100.0, 100.0, 0.0, 10.0),
        MagneticCore("Planar E 14 - N87", "Planar E", "N87", 2200, 12.2, 31.0, 0.20, 0.32, 2.4e-3),
        MagneticCore("Planar E 18 - N87", "Planar E", "N87", 2200, 22.5, 39.5, 0.25, 0.32, 2.4e-3),
        MagneticCore("Planar E 22 - 3C95", "Planar E", "3C95", 3000, 41.0, 48.0, 0.30, 0.39, 1.8e-3),
        MagneticCore("Planar E 32 - 3C97", "Planar E", "3C97", 3000, 83.0, 70.0, 0.40, 0.41, 1.5e-3),
        MagneticCore("RM 5 - N49", "RM", "N49", 1500, 16.0, 38.0, 0.20, 0.45, 2.8e-3),
        MagneticCore("RM 8 - N87", "RM", "N87", 2200, 52.0, 58.0, 0.30, 0.32, 2.4e-3),
        MagneticCore("Pot 14 - 3F3", "Pot", "3F3", 1800, 23.0, 30.0, 0.20, 0.36, 2.0e-3),
        MagneticCore("Pot 22 - N87", "Pot", "N87", 2200, 63.0, 45.0, 0.30, 0.32, 2.4e-3),
        MagneticCore("Toroid 10 - 4F1", "Toroid", "4F1", 80, 7.0, 23.0, 0.0, 0.30, 1.1e-3),
        MagneticCore("Toroid 20 - KoolMu 60", "Toroid", "KoolMu", 60, 29.0, 47.0, 0.0, 1.00, 8e-4),
        MagneticCore("C core 25 - nanocrystalline", "C", "Nano", 30000, 72.0, 96.0, 0.50, 1.20, 4e-4),
    )
}


@dataclass(frozen=True)
class CoilSpec:
    shape: str = "Rectangular spiral"
    outer_width_mm: float = 35.0
    outer_height_mm: float = 35.0
    turns: int = 8
    trace_width_mm: float = 0.5
    spacing_mm: float = 0.25
    copper_um: float = 35.0
    layers: int = 2
    layer_connection: str = "Series"
    frequency_khz: float = 100.0
    current_a: float = 0.5
    voltage_v: float = 5.0
    core_name: str = "Air / no core"
    secondary_turns: int = 0
    secondary_layers: int = 1
    coupling: float = 0.90
    external_field_ut: float = 50.0


@dataclass(frozen=True)
class MotionSpec:
    """Lumped 1-DOF actuator mechanics and drive definition."""
    moving_mass_kg: float = 1e-6
    spring_n_m: float = 1.0
    mechanical_q: float = 20.0
    damping_ns_m: float = 0.0
    initial_gap_m: float = 5e-4
    stroke_limit_m: float = 1e-3
    load_force_n: float = 0.0
    static_friction_n: float = 0.0
    drive_mode: str = "Voltage step"
    drive_frequency_hz: float = 100.0
    duration_s: float = 0.02
    time_step_s: float = 2e-6
    temperature_k: float = 293.15
    rotor_inertia_kg_m2: float = 1e-10
    angular_stiffness_nm_rad: float = 0.0


@dataclass(frozen=True)
class MotionSample:
    time_s: float
    displacement_m: float
    velocity_m_s: float
    acceleration_m_s2: float
    current_a: float
    force_n: float


@dataclass
class DynamicsResult:
    samples: list[MotionSample]
    peak_force_n: float
    peak_acceleration_m_s2: float
    peak_speed_m_s: float
    peak_displacement_m: float
    final_displacement_m: float
    natural_frequency_hz: float
    damping_ns_m: float
    settling_time_s: float | None
    force_constant_n_a: float
    force_gradient_n_m: float
    thermal_force_noise_n_sqrt_hz: float
    brownian_displacement_rms_m: float
    mode: str
    validity: str
    warnings: list[str]


@dataclass(frozen=True)
class WindingSegment:
    x1_mm: float
    y1_mm: float
    x2_mm: float
    y2_mm: float
    width_mm: float
    layer: int
    winding: str = "Primary"

    @property
    def length_mm(self): return math.hypot(self.x2_mm-self.x1_mm,self.y2_mm-self.y1_mm)


@dataclass(frozen=True)
class WindingVia:
    x_mm: float
    y_mm: float
    from_layer: int
    to_layer: int
    winding: str = "Primary"


@dataclass
class MagneticResult:
    spec: CoilSpec
    core: MagneticCore
    segments: list[WindingSegment]
    vias: list[WindingVia]
    conductor_length_mm: float
    resistance_dc_ohm: float
    resistance_ac_ohm: float
    inductance_uh: float
    capacitance_pf: float
    self_resonance_mhz: float
    quality_factor: float
    field_center_mt: float
    saturation_current_a: float
    copper_loss_w: float
    core_loss_w: float
    secondary_inductance_uh: float = 0.0
    mutual_inductance_uh: float = 0.0
    turns_ratio: float = 0.0
    force_n: float = 0.0
    travel_mm: float = 0.0
    torque_unm: float = 0.0
    notes: list[str] | None = None
    dynamics: DynamicsResult | None = None


def load_core_catalog(path: str | Path) -> dict[str, MagneticCore]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("cores", payload)
    result = dict(CORE_CATALOG)
    for row in rows:
        core = MagneticCore(**row); result[core.name] = core
    return result


def save_core_catalog(path: str | Path, cores: dict[str, MagneticCore]) -> None:
    Path(path).write_text(json.dumps({"cores":[asdict(core) for core in cores.values()]},indent=2),encoding="utf-8")


class MagneticsEngine:
    @staticmethod
    def analyze(spec: CoilSpec, core_catalog: dict[str, MagneticCore] | None = None,
                actuator: str = "Voice coil") -> MagneticResult:
        catalog = core_catalog or CORE_CATALOG
        if spec.core_name not in catalog: raise ValueError(f"Unknown magnetic core: {spec.core_name}")
        if min(spec.outer_width_mm,spec.outer_height_mm,spec.turns,spec.trace_width_mm,spec.copper_um,spec.layers) <= 0:
            raise ValueError("Winding dimensions, turns, copper, and layers must be positive.")
        total_layers = spec.layers + (spec.secondary_layers if spec.secondary_turns else 0)
        if total_layers > 16 or not 0 < spec.coupling <= 1:
            raise ValueError("Layers must be at most 16 and coupling must be in (0, 1].")
        pitch=spec.trace_width_mm+spec.spacing_mm
        if 2*max(spec.turns,spec.secondary_turns)*pitch >= min(spec.outer_width_mm,spec.outer_height_mm):
            raise ValueError("The selected turns do not fit inside the winding outline.")
        primary_layers=[]
        for layer in range(spec.layers):
            segments=MagneticsEngine._circular(spec,layer) if spec.shape=="Circular spiral" else MagneticsEngine._rectangular(spec,layer)
            primary_layers.append(segments)
        segments=[item for layer in primary_layers for item in layer];vias=[]
        if spec.layer_connection=="Series":
            for layer in range(spec.layers-1):
                end=primary_layers[layer][-1];vias.append(WindingVia(end.x2_mm,end.y2_mm,layer,layer+1))
        secondary_segments=[];secondary_vias=[]
        if spec.secondary_turns:
            secondary_spec=replace(spec,turns=spec.secondary_turns)
            secondary_layers=[]
            for offset in range(spec.secondary_layers):
                layer=spec.layers+offset
                winding=MagneticsEngine._circular(secondary_spec,layer,"Secondary") if spec.shape=="Circular spiral" else MagneticsEngine._rectangular(secondary_spec,layer,"Secondary")
                secondary_layers.append(winding);secondary_segments.extend(winding)
            for offset in range(spec.secondary_layers-1):
                end=secondary_layers[offset][-1];secondary_vias.append(WindingVia(end.x2_mm,end.y2_mm,spec.layers+offset,spec.layers+offset+1,"Secondary"))
            segments.extend(secondary_segments);vias.extend(secondary_vias)
        primary_length=sum(item.length_mm for layer in primary_layers for item in layer)+1.6*max(0,spec.layers-1 if spec.layer_connection=="Series" else 0)
        secondary_length=sum(item.length_mm for item in secondary_segments)+1.6*len(secondary_vias)
        length_mm=primary_length+secondary_length
        copper_area=(spec.trace_width_mm/1000)*(spec.copper_um*1e-6)
        rdc=COPPER_RHO*(primary_length/1000)/copper_area
        if spec.layer_connection=="Parallel":rdc/=spec.layers*spec.layers
        frequency=max(spec.frequency_khz*1000,1.0);omega=2*math.pi*frequency
        skin=math.sqrt(2*COPPER_RHO/(omega*MU0));thickness=spec.copper_um*1e-6
        skin_factor=max(1.0,thickness/max(2*skin,1e-12));proximity=1+0.018*spec.turns*spec.layers*spec.trace_width_mm/max(spec.spacing_mm+spec.trace_width_mm,0.01)
        rac=rdc*skin_factor*proximity
        layer_turns=spec.turns;effective_turns=layer_turns*spec.layers if spec.layer_connection=="Series" else layer_turns
        core=catalog[spec.core_name];inductance=MagneticsEngine._inductance(spec,effective_turns,core)
        avg_perimeter=2*(spec.outer_width_mm+spec.outer_height_mm-2*spec.turns*pitch)/1000
        capacitance=EPS0*4.2*(length_mm/1000)*(spec.trace_width_mm/1000)/max(spec.spacing_mm/1000,25e-6)
        capacitance*=1+0.35*(spec.layers-1)
        srf=1/(2*math.pi*math.sqrt(max(inductance*1e-6*capacitance,1e-30)))/1e6
        q=omega*(inductance*1e-6)/max(rac,1e-12)
        reluctance=MagneticsEngine._reluctance(core);flux=effective_turns*spec.current_a/max(reluctance,1e-12);field=min(flux/(core.effective_area_mm2*1e-6),core.saturation_t)
        saturation=core.saturation_t*core.effective_area_mm2*1e-6*reluctance/max(effective_turns,1)
        copper_loss=spec.current_a**2*rac
        volume_cm3=core.effective_area_mm2*core.path_length_mm/1000.0
        core_loss=core.loss_k*(max(spec.frequency_khz,0.001)/100.0)**core.loss_alpha*(max(field,1e-6)/0.1)**core.loss_beta*volume_cm3
        secondary=mutual=ratio=0.0
        if spec.secondary_turns>0:
            secondary_effective=spec.secondary_turns*spec.secondary_layers
            ratio=secondary_effective/max(effective_turns,1);secondary=inductance*ratio*ratio;mutual=spec.coupling*math.sqrt(inductance*secondary)
        area_m2=spec.outer_width_mm*spec.outer_height_mm*1e-6
        wire_active=max(avg_perimeter*effective_turns,1e-6)
        if actuator=="Linear solenoid":force=field*field*(core.effective_area_mm2*1e-6)/(2*MU0);travel=min(spec.outer_width_mm,spec.outer_height_mm)*0.25
        elif actuator=="PCB magnetic torquer":force=0.0;travel=0.0
        else:force=field*spec.current_a*wire_active;travel=min(spec.outer_width_mm,spec.outer_height_mm)*0.15
        torque=effective_turns*spec.current_a*area_m2*(spec.external_field_ut*1e-6)*1e6
        notes=["Inductance uses planar Wheeler/Mohan or magnetic-reluctance approximations.","AC resistance includes first-order skin and proximity multipliers; validate at frequency with an impedance analyzer.","Field, force, torque, saturation, and core loss are reduced-order estimates and require FEA plus prototype correlation."]
        return MagneticResult(spec,core,segments,vias,length_mm,rdc,rac,inductance,capacitance*1e12,srf,q,field*1000,saturation,copper_loss,core_loss,secondary,mutual,ratio,force,travel,torque,notes)

    @staticmethod
    def simulate_dynamics(result: MagneticResult, motion: MotionSpec,
                          actuator: str = "Voice coil") -> DynamicsResult:
        """Integrate a coupled coil/1-DOF mechanical model with hard travel stops."""
        if min(motion.moving_mass_kg, motion.spring_n_m, motion.mechanical_q,
               motion.initial_gap_m, motion.stroke_limit_m, motion.duration_s,
               motion.time_step_s, motion.temperature_k) <= 0:
            raise ValueError("Mass, stiffness, Q, gap, stroke, duration, time step, and temperature must be positive.")
        rotating = actuator in ("PCB coil motor", "PCB magnetic torquer")
        inertia = motion.rotor_inertia_kg_m2
        if rotating and inertia <= 0: raise ValueError("Rotor inertia must be positive for rotary actuators.")
        mass = inertia if rotating else motion.moving_mass_kg
        stiffness = motion.angular_stiffness_nm_rad if rotating else motion.spring_n_m
        if stiffness < 0: raise ValueError("Mechanical stiffness cannot be negative.")
        omega_n = math.sqrt(stiffness / mass) if stiffness else 0.0
        damping = motion.damping_ns_m if motion.damping_ns_m > 0 else (
            mass * omega_n / motion.mechanical_q if omega_n else 0.0)
        natural_hz = omega_n / (2 * math.pi)
        inductance_h = max(result.inductance_uh * 1e-6, 1e-12)
        resistance = max(result.resistance_ac_ohm, 1e-9)
        electrical_tau = inductance_h / resistance
        requested_dt = motion.time_step_s
        stable_dt = requested_dt
        if natural_hz: stable_dt = min(stable_dt, 1 / (80 * natural_hz))
        stable_dt = min(stable_dt, electrical_tau / 25)
        steps = math.ceil(motion.duration_s / stable_dt)
        if steps > 200000:
            raise ValueError("Dynamics requires more than 200,000 integration steps; shorten duration or use a coarser validated model.")
        dt = motion.duration_s / max(steps, 1)
        output_stride = max(1, math.ceil(steps / 5000))
        effective_turns = result.spec.turns * result.spec.layers if result.spec.layer_connection == "Series" else result.spec.turns
        active_length = max(2 * (result.spec.outer_width_mm + result.spec.outer_height_mm) / 1000 * effective_turns, 1e-9)
        base_force_constant = max(result.field_center_mt * 1e-3 * active_length, 0.0)
        torque_constant = effective_turns * result.spec.outer_width_mm * result.spec.outer_height_mm * 1e-6 * result.spec.external_field_ut * 1e-6

        def drive(t):
            sine = math.sin(2 * math.pi * motion.drive_frequency_hz * t)
            if motion.drive_mode == "Voltage sine": return result.spec.voltage_v * sine, None
            if motion.drive_mode == "Current step": return 0.0, result.spec.current_a
            if motion.drive_mode == "Current sine": return 0.0, result.spec.current_a * sine
            return result.spec.voltage_v, None

        def magnetic_effort(position, current):
            if rotating:
                return torque_constant * current
            if actuator == "Linear solenoid":
                area = max(result.core.effective_area_mm2 * 1e-6, 1e-12)
                fixed_reluctance = result.core.path_length_mm / 1000 / (
                    MU0 * max(result.core.permeability, 1) * area)
                gap = max(motion.initial_gap_m - position, max(motion.initial_gap_m * 1e-4, 1e-9))
                reluctance = fixed_reluctance + gap / (MU0 * area)
                dldx = effective_turns ** 2 / (MU0 * area * reluctance ** 2)
                effort = 0.5 * current ** 2 * dldx
                saturation_force = result.core.saturation_t ** 2 * area / (2 * MU0)
                return min(effort, saturation_force)
            rolloff = max(motion.initial_gap_m, 1e-12)
            return base_force_constant * current / (1 + (position / rolloff) ** 2)

        def derivative(t, state):
            position, speed, current = state
            voltage, commanded_current = drive(t)
            if commanded_current is None:
                back_emf = (torque_constant if rotating else base_force_constant) * speed
                current_rate = (voltage - resistance * current - back_emf) / inductance_h
            else:
                current = commanded_current; current_rate = 0.0
            effort = magnetic_effort(position, current)
            opposing = stiffness * position + damping * speed
            if not rotating:
                opposing += motion.load_force_n
                if abs(speed) < 1e-12 and abs(effort - opposing) <= motion.static_friction_n:
                    acceleration = 0.0
                else:
                    friction = math.copysign(motion.static_friction_n, speed or effort - opposing)
                    acceleration = (effort - opposing - friction) / mass
            else:
                acceleration = (effort - opposing) / mass
            return (speed, acceleration, current_rate), current, effort

        state = [0.0, 0.0, 0.0]; samples = []
        peak_force = peak_acceleration = peak_speed = peak_displacement = 0.0
        for step in range(steps + 1):
            t = min(step * dt, motion.duration_s)
            first, current, effort = derivative(t, state)
            acceleration = first[1]
            if step % output_stride == 0 or step == steps:
                samples.append(MotionSample(t, state[0], state[1], acceleration, current, effort))
            peak_force = max(peak_force, abs(effort)); peak_acceleration = max(peak_acceleration, abs(acceleration))
            peak_speed = max(peak_speed, abs(state[1])); peak_displacement = max(peak_displacement, abs(state[0]))
            if step == steps: break
            k1 = first
            s2 = [state[i] + dt * k1[i] / 2 for i in range(3)]; k2 = derivative(t + dt / 2, s2)[0]
            s3 = [state[i] + dt * k2[i] / 2 for i in range(3)]; k3 = derivative(t + dt / 2, s3)[0]
            s4 = [state[i] + dt * k3[i] for i in range(3)]; k4 = derivative(t + dt, s4)[0]
            state = [state[i] + dt * (k1[i] + 2*k2[i] + 2*k3[i] + k4[i]) / 6 for i in range(3)]
            limit = motion.stroke_limit_m
            if abs(state[0]) > limit:
                state[0] = math.copysign(limit, state[0])
                if state[1] * state[0] > 0: state[1] = 0.0
            if not all(math.isfinite(value) for value in state):
                raise ValueError("Dynamics diverged; reduce the time step or review mechanical/electrical parameters.")

        final = state[0]; tolerance = max(abs(final) * 0.02, motion.stroke_limit_m * 1e-4)
        settling = None
        for index, sample in enumerate(samples):
            if all(abs(other.displacement_m - final) <= tolerance for other in samples[index:]):
                settling = sample.time_s; break
        delta = max(motion.initial_gap_m * 1e-5, 1e-12)
        gradient = (magnetic_effort(delta, result.spec.current_a) -
                    magnetic_effort(-delta, result.spec.current_a)) / (2 * delta)
        thermal_force = math.sqrt(max(4 * BOLTZMANN * motion.temperature_k * damping, 0.0))
        brownian = math.sqrt(BOLTZMANN * motion.temperature_k / stiffness) if stiffness else math.inf
        warnings = []
        nanoscale = motion.stroke_limit_m <= 1e-6 or motion.initial_gap_m <= 1e-6 or motion.moving_mass_kg <= 1e-12
        if nanoscale:
            warnings.extend([
                "Nanoscale screening only: continuum material, bulk magnetic, and lumped damping assumptions may fail.",
                "Model omits squeeze-film/rarefied-gas damping, adhesion, stiction, Casimir/van der Waals forces, process stress, and modal coupling.",
                "Use process-calibrated multiphysics FEA and measured material/device parameters before fabrication.",
            ])
        if peak_displacement >= motion.stroke_limit_m * 0.999:
            warnings.append("Travel stop reached; impact/contact dynamics are not modeled.")
        if result.spec.frequency_khz * 1000 >= result.self_resonance_mhz * 1e6 / 5:
            warnings.append("Electrical drive approaches winding self resonance; the lumped coil model is unreliable.")
        validity = "NANOSCALE SCREENING ONLY" if nanoscale else "REDUCED-ORDER ENGINEERING ESTIMATE"
        dynamics = DynamicsResult(samples, peak_force, peak_acceleration, peak_speed,
                                  peak_displacement, final, natural_hz, damping, settling,
                                  torque_constant if rotating else base_force_constant,
                                  gradient, thermal_force, brownian,
                                  "Rotary" if rotating else "Linear", validity, warnings)
        result.dynamics = dynamics
        return dynamics

    @staticmethod
    def _rectangular(spec: CoilSpec, layer: int, winding: str = "Primary") -> list[WindingSegment]:
        pitch=spec.trace_width_mm+spec.spacing_mm;points=[]
        for turn in range(spec.turns):
            inset=spec.trace_width_mm/2+turn*pitch;left=inset;right=spec.outer_width_mm-inset;bottom=inset;top=spec.outer_height_mm-inset
            ring=[(left,bottom),(right,bottom),(right,top),(left,top)]
            if turn%2: ring.reverse()
            points.extend(ring)
        linked=[]
        for index,p in enumerate(points):
            if index:linked.append(WindingSegment(*points[index-1],*p,spec.trace_width_mm,layer,winding))
        return linked

    @staticmethod
    def _circular(spec: CoilSpec, layer: int, winding: str = "Primary") -> list[WindingSegment]:
        pitch=spec.trace_width_mm+spec.spacing_mm;cx=spec.outer_width_mm/2;cy=spec.outer_height_mm/2;r0=min(spec.outer_width_mm,spec.outer_height_mm)/2-spec.trace_width_mm/2;steps=max(80,spec.turns*40);points=[]
        for i in range(steps+1):
            theta=2*math.pi*spec.turns*i/steps;radius=r0-pitch*spec.turns*i/steps;points.append((cx+radius*math.cos(theta),cy+radius*math.sin(theta)))
        return [WindingSegment(*a,*b,spec.trace_width_mm,layer,winding) for a,b in zip(points,points[1:])]

    @staticmethod
    def _reluctance(core: MagneticCore) -> float:
        area=max(core.effective_area_mm2*1e-6,1e-12);magnetic=core.path_length_mm/1000/(MU0*max(core.permeability,1)*area);gap=core.gap_mm/1000/(MU0*area);return magnetic+gap

    @staticmethod
    def _inductance(spec: CoilSpec, turns: int, core: MagneticCore) -> float:
        if core.family != "Air":return turns*turns/ MagneticsEngine._reluctance(core)*1e6
        dout=(spec.outer_width_mm+spec.outer_height_mm)/2/1000;din=max(dout-2*spec.turns*(spec.trace_width_mm+spec.spacing_mm)/1000,1e-5);davg=(dout+din)/2;fill=(dout-din)/(dout+din)
        if spec.shape=="Circular spiral":c1,c2,c3,c4=1.0,2.46,0.0,0.20
        else:c1,c2,c3,c4=1.27,2.07,0.18,0.13
        return MU0*turns*turns*davg*c1/2*(math.log(c2/max(fill,1e-6))+c3*fill+c4*fill*fill)*1e6
