"""Backward-Euler spatial thermal evolution over an assembled conductance graph."""
import math
import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu

SIGMA = 5.670374419e-8

def evolve(laplacian, capacity, source_vectors, surface_area, h, emissivity,
           ambient, contact_g, contact_rhs, fixed, settings):
    """Integrate C dT/dt + K T + boundary loss = explicit scheduled power.

    Capacity is J/K per node; sources are W per reference. Schedule entries are
    [time_s, multiplier] with linear interpolation and held endpoint values.
    Radiation is Newton-linearized; the linear sparse factorization is reused.
    """
    def finite(key, default=None, positive=False):
        value=float(settings.get(key, default))
        if not math.isfinite(value) or (positive and value <= 0):
            raise ValueError(key + " must be finite and positive.")
        return value
    duration=finite("duration_s", positive=True)
    dt=finite("timestep_s", positive=True)
    initial=finite("initial_c", ambient)
    if initial <= -273.15:
        raise ValueError("Initial temperature must exceed absolute zero.")
    steps=math.ceil(duration/dt)
    if steps > 10000:
        raise ValueError("Transient exceeds 10000 steps; increase timestep_s.")
    stride=settings.get("frame_stride", max(1, math.ceil(steps/100)))
    if isinstance(stride, bool) or not isinstance(stride,int) or stride < 1 or math.ceil(steps/stride)>200:
        raise ValueError("frame_stride must limit stored frames to 200.")
    capacity=np.asarray(capacity,dtype=float)
    if np.any(~np.isfinite(capacity)) or np.any(capacity<=0):
        raise ValueError("Every thermal node needs explicit positive heat capacity.")
    schedules=settings.get("power_schedules", {})
    if not isinstance(schedules, dict):
        raise ValueError("power_schedules must map selected references to points.")
    if set(schedules)-set(source_vectors):
        raise ValueError("Power schedule references must be selected heat sources.")
    for ref, points in schedules.items():
        if not points or any(len(p)!=2 or not all(math.isfinite(float(x)) for x in p) or p[0]<0 or p[1]<0 for p in points):
            raise ValueError(ref + ": schedule requires finite nonnegative [time_s, multiplier] entries.")
        if any(b[0]<=a[0] for a,b in zip(points,points[1:])):
            raise ValueError("Schedule times must strictly increase.")
    n=len(capacity)
    if (math.ceil(steps/stride)+1)*n > 5000000:
        raise ValueError("Transient exceeds five million stored node values; increase frame_stride.")
    ids=np.array(sorted(fixed),dtype=int)
    free=np.array([i for i in range(n) if i not in fixed],dtype=int)
    temp=np.full(n,initial)
    for i,v in fixed.items(): temp[i]=v
    frames=[{"time_s":0.0,"temperatures_c":temp.tolist()}]
    energy=[]
    cache={}
    for step in range(1,steps+1):
        time_s=min(step*dt,duration)
        delta=time_s-(step-1)*dt
        source=np.zeros(n)
        for ref, vector in source_vectors.items():
            points=schedules.get(ref)
            scale=float(np.interp(time_s,[p[0] for p in points],[p[1] for p in points])) if points else 1.0
            source+=np.asarray(vector)*scale
        previous=temp.copy()
        mass=capacity/delta
        for iteration in range(40):
            kelvin=temp+273.15
            loss=surface_area*(h*(temp-ambient)+emissivity*SIGMA*(kelvin**4-(ambient+273.15)**4))
            slope=surface_area*(h+4*emissivity*SIGMA*kelvin**3)
            matrix=laplacian+diags(mass+contact_g+slope,format="csc")
            rhs=source+contact_rhs+mass*previous+slope*temp-loss
            if len(ids): rhs[free]-=matrix[free][:,ids]@temp[ids]
            key=delta if not np.any(emissivity) else None
            factor=cache.get(key) if key is not None else None
            if factor is None:
                factor=splu(matrix[free][:,free].tocsc()) if len(free) else None
                if key is not None: cache[key]=factor
            candidate=factor.solve(rhs[free]) if len(free) else np.array([])
            if not np.all(np.isfinite(candidate)) or np.any(candidate <= -273.15) or np.any(candidate > 10000):
                raise ValueError("Transient thermal solve diverged.")
            change=max(np.abs(candidate-temp[free]),default=0)
            temp[free]=candidate
            if change < 1e-7: break
        else: raise ValueError("Transient radiation iteration did not converge.")
        loss=surface_area*(h*(temp-ambient)+emissivity*SIGMA*((temp+273.15)**4-(ambient+273.15)**4))
        contact=contact_g*temp-contact_rhs
        rate=capacity*(temp-previous)/delta
        equation=rate+laplacian@temp+loss+contact-source
        fixture=-float(np.sum(equation[ids])) if len(ids) else 0.0
        residual=float(np.sum(source-rate-loss-contact))-fixture
        tolerance=max(1e-7, abs(float(np.sum(source)))*1e-6)
        if abs(residual)>tolerance:
            raise ArithmeticError("Transient step failed energy balance; refine or inspect boundary inputs.")
        energy.append({"time_s":time_s,"input_w":float(np.sum(source)),"stored_energy_change_j":float(np.sum(rate)*delta),"boundary_loss_w":float(np.sum(loss+contact))+fixture,"residual_w":residual})
        if step%stride==0 or step==steps:
            frames.append({"time_s":time_s,"temperatures_c":temp.tolist()})
    return {"model":"backward-Euler spatial thermal transient", "status":"completed", "frames":frames,"power_schedules":schedules,"energy_balance":energy,"max_energy_residual_w":max(abs(r["residual_w"]) for r in energy),"steps":steps,"timestep_s":dt,"final_temperatures_c":temp.tolist(),"assumptions":["Explicit volumetric heat capacities; no package die thermal capacity or circuit electrothermal feedback. Copper raster occupancy and laminate slabs approximate storage; barrel metal storage and coating storage are unresolved.","Scheduled multipliers linearly interpolate declared dissipations; no operating losses are inferred.","Time-step convergence must be checked independently; implicit stability does not establish accuracy."]}
