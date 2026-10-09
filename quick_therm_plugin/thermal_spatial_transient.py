"""Backward-Euler spatial thermal evolution over an assembled conductance graph."""
import math
from collections.abc import Mapping

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu

SIGMA = 5.670374419e-8


def _finite(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(label + " must be a finite number.")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " must be a finite number.") from exc
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(label + " is outside its finite physical range.")
    return value


def evolve(laplacian, capacity, source_vectors, surface_area, h, emissivity,
           ambient, contact_g, contact_rhs, fixed, settings):
    """Integrate C dT/dt + K T + boundary loss = explicit scheduled power.

    Capacity is J/K per node; sources are W per reference. Schedule entries are
    [time_s, multiplier] with held endpoint values. The default interpolation
    is linear; 'step' holds each multiplier until the next declared event.
    Integration lands on every schedule knot and uses exact interval-average
    input power. Conductive/radiative losses use the backward-Euler endpoint.
    Radiation is Newton-linearized; the linear sparse factorization is reused.
    """
    if not isinstance(settings, Mapping):
        raise ValueError("Transient settings must be a mapping.")
    duration = _finite(settings.get("duration_s"), "duration_s", positive=True)
    dt = _finite(settings.get("timestep_s"), "timestep_s", positive=True)
    ambient = _finite(ambient, "Ambient temperature")
    initial = _finite(settings.get("initial_c", ambient), "Initial temperature")
    if min(initial, ambient) <= -273.15 or initial > 10000:
        raise ValueError("Initial/ambient temperatures must exceed absolute zero; initial_c must not exceed 10000 C.")
    ratio = duration/dt
    if not math.isfinite(ratio) or ratio > 10000:
        raise ValueError("Transient exceeds 10000 steps; increase timestep_s.")
    try:
        capacity = np.asarray(capacity, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Every thermal node needs explicit positive heat capacity.") from exc
    if capacity.ndim != 1 or not len(capacity) or np.any(~np.isfinite(capacity)) or np.any(capacity <= 0):
        raise ValueError("Every thermal node needs explicit positive heat capacity.")
    n = len(capacity)

    def vector(value, label, nonnegative=True):
        try:
            value = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(label + " requires one finite value per thermal node.") from exc
        if value.shape != (n,) or not np.all(np.isfinite(value)) or (nonnegative and np.any(value < 0)):
            raise ValueError(label + " requires one finite " + ("nonnegative " if nonnegative else "") + "value per thermal node.")
        return value

    surface_area = vector(surface_area, "Exposed area")
    h = vector(h, "Convection coefficient")
    emissivity = vector(emissivity, "Emissivity")
    if np.any(emissivity > 1):
        raise ValueError("Emissivity must be between zero and one.")
    contact_g = vector(contact_g, "Contact conductance")
    contact_rhs = vector(contact_rhs, "Contact boundary term", nonnegative=False)
    if getattr(laplacian, "shape", None) != (n, n) or not hasattr(laplacian, "tocsr"):
        raise ValueError("Thermal conductance matrix must be a sparse square matrix matching node capacity.")
    laplacian = laplacian.tocsr()
    if not np.all(np.isfinite(laplacian.data)):
        raise ValueError("Thermal conductance matrix must be finite.")
    if not isinstance(source_vectors, Mapping) or any(not isinstance(ref, str) or not ref for ref in source_vectors):
        raise ValueError("Heat sources must map nonempty reference names to node powers.")
    source_vectors = {ref: vector(value, ref + " source power") for ref, value in source_vectors.items()}
    if not isinstance(fixed, Mapping):
        raise ValueError("Fixed temperatures must map thermal node indices to temperatures.")
    validated_fixed = {}
    for index, value in fixed.items():
        if isinstance(index, (bool, np.bool_)) or not isinstance(index, (int, np.integer)) or not 0 <= index < n:
            raise ValueError("Fixed temperature node index is outside the thermal model.")
        value = _finite(value, "Fixed temperature")
        if not -273.15 < value <= 10000:
            raise ValueError("Fixed temperature must exceed absolute zero and not exceed 10000 C.")
        validated_fixed[int(index)] = value
    fixed = validated_fixed
    schedules = settings.get("power_schedules", {})
    if not isinstance(schedules, Mapping):
        raise ValueError("power_schedules must map selected references to points.")
    if set(schedules)-set(source_vectors):
        raise ValueError("Power schedule references must be selected heat sources.")
    interpolation = settings.get("schedule_interpolation", "linear")
    if interpolation not in ("linear", "step"):
        raise ValueError("schedule_interpolation must be linear or step.")
    normalized = {}
    events = set()
    for ref, points in schedules.items():
        if not isinstance(points, (list, tuple)) or not points:
            raise ValueError(ref + ": schedule requires nonempty [time_s, multiplier] entries.")
        rows = []
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError(ref + ": schedule requires [time_s, multiplier] entries.")
            rows.append([_finite(value, ref + " schedule value", nonnegative=True) for value in point])
        if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
            raise ValueError("Schedule times must strictly increase.")
        normalized[ref] = rows
        events.update(row[0] for row in rows if 0 < row[0] < duration)
    schedules = normalized
    timeline = {0., duration, *events}
    for step in range(1, math.ceil(ratio)):
        value = step*dt
        if value < duration:
            timeline.add(value)
    # Replace only rounding-equivalent regular samples. Distinct schedule
    # events must retain their exact timing and their intervening input energy.
    for event in (*events, duration):
        nearest = round(event/dt)*dt
        if nearest in timeline and nearest not in events and nearest not in (0., duration):
            if abs(nearest-event) <= 8*max(math.ulp(nearest), math.ulp(event)):
                timeline.remove(nearest)
    timeline = sorted(timeline)
    steps = len(timeline)-1
    if steps > 10000:
        raise ValueError("Transient including schedule events exceeds 10000 steps; simplify schedules or increase timestep_s.")
    stride = settings.get("frame_stride", max(1, math.ceil(steps/100)))
    if isinstance(stride, bool) or not isinstance(stride, int) or stride < 1 or math.ceil(steps/stride)+1 > 200:
        raise ValueError("frame_stride must limit stored frames, including the initial frame, to 200.")
    stored_steps={index for index, endpoint in enumerate(timeline[1:],1)
                  if index % stride == 0 or index == steps or endpoint in events}
    if len(stored_steps)+1 > 200:
        raise ValueError('Stored frames including schedule events exceed 200; simplify schedules or increase frame_stride.')
    if (len(stored_steps)+1)*n > 5000000:
        raise ValueError("Transient exceeds five million stored node values; increase frame_stride.")
    ids = np.array(sorted(fixed), dtype=int)
    free = np.array([i for i in range(n) if i not in fixed], dtype=int)
    temp = np.full(n, initial)
    for i, v in fixed.items():
        temp[i] = v
    frames = [{"time_s": 0.0, "temperatures_c": temp.tolist()}]
    energy = []
    cache = {}
    for step, (start, time_s) in enumerate(zip(timeline, timeline[1:]), 1):
        delta = time_s-start
        source = np.zeros(n)
        for ref, source_vector in source_vectors.items():
            points = schedules.get(ref)
            scale = 1.0
            if points:
                times, multipliers = zip(*points)
                if interpolation == "step":
                    # The new multiplier applies AT the event, after the
                    # preceding interval has deposited its old held power.
                    index = max(0, int(np.searchsorted(times, start, side="right"))-1)
                    scale = multipliers[index]
                else:
                    scale = .5*float(np.interp(start, times, multipliers)) + .5*float(np.interp(time_s, times, multipliers))
            source += source_vector*scale
        if not np.all(np.isfinite(source)):
            raise ValueError("Scheduled source power exceeds the finite numerical range.")
        previous = temp.copy()
        mass = capacity/delta
        if not np.all(np.isfinite(mass)):
            raise ValueError("Transient interval is too small for the declared heat capacities.")
        for iteration in range(40):
            kelvin = temp+273.15
            loss = surface_area*(h*(temp-ambient)+emissivity*SIGMA*(kelvin**4-(ambient+273.15)**4))
            slope = surface_area*(h+4*emissivity*SIGMA*kelvin**3)
            matrix = laplacian+diags(mass+contact_g+slope, format="csc")
            rhs = source+contact_rhs+mass*previous+slope*temp-loss
            if len(ids):
                rhs[free] -= matrix[free][:, ids]@temp[ids]
            key = delta if not np.any(emissivity) else None
            factor = cache.get(key) if key is not None else None
            if factor is None:
                factor = splu(matrix[free][:, free].tocsc()) if len(free) else None
                if key is not None:
                    cache[key] = factor
                    if len(cache) > 128:
                        cache.pop(next(iter(cache)))
            candidate = factor.solve(rhs[free]) if len(free) else np.array([])
            if not np.all(np.isfinite(candidate)) or np.any(candidate <= -273.15) or np.any(candidate > 10000):
                raise ValueError("Transient thermal solve diverged.")
            change = max(np.abs(candidate-temp[free]), default=0)
            temp[free] = candidate
            if change < 1e-7:
                break
        else:
            raise ValueError("Transient radiation iteration did not converge.")
        loss = surface_area*(h*(temp-ambient)+emissivity*SIGMA*((temp+273.15)**4-(ambient+273.15)**4))
        contact = contact_g*temp-contact_rhs
        rate = capacity*(temp-previous)/delta
        equation = rate+laplacian@temp+loss+contact-source
        fixture = -float(np.sum(equation[ids])) if len(ids) else 0.0
        residual = float(np.sum(source-rate-loss-contact))-fixture
        tolerance = max(1e-7, abs(float(np.sum(source)))*1e-6)
        if not math.isfinite(residual) or abs(residual) > tolerance:
            raise ArithmeticError("Transient step failed energy balance; refine or inspect boundary inputs.")
        input_w = float(np.sum(source))
        boundary_w = float(np.sum(loss+contact))+fixture
        energy.append({"time_s": time_s, "elapsed_s": delta, "input_w": input_w,
                       "input_energy_j": input_w*delta,
                       "stored_energy_change_j": float(np.sum(rate)*delta),
                       "boundary_loss_w": boundary_w, "boundary_energy_j": boundary_w*delta,
                       "residual_w": residual})
        if step in stored_steps:
            frames.append({"time_s": time_s, "temperatures_c": temp.tolist()})
    return {"model": "backward-Euler spatial thermal transient", "status": "completed",
            "frames": frames, "power_schedules": schedules, "schedule_interpolation": interpolation,
            "energy_balance": energy, "max_energy_residual_w": max(abs(r["residual_w"]) for r in energy),
            "steps": steps, "timestep_s": dt, "final_temperatures_c": temp.tolist(),
            "assumptions": [
                "Explicit volumetric heat capacities; no package die thermal capacity or circuit electrothermal feedback. Copper raster occupancy and laminate slabs approximate storage; barrel metal storage and coating storage are unresolved.",
                "Scheduled multipliers use declared " + interpolation + " interpolation and held endpoint values; integration lands on schedule knots and preserves their interval input energy. No operating losses are inferred.",
                "Conductive, convective and radiative loss use backward-Euler endpoint temperatures; time-step convergence must be checked independently. Implicit stability and energy balance do not establish accuracy."]}
