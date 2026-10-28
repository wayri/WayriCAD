"""Backward-Euler spatial thermal evolution over an assembled conductance graph."""
import math
import bisect
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
           ambient, contact_g, contact_rhs, fixed, settings, *, initial_temperatures_c=None):
    """Integrate C dT/dt + K T + boundary loss = explicit scheduled power.

    Capacity is J/K per node; sources are W per reference. Schedule entries are
    [time_s, multiplier] with held endpoint values. The default interpolation
    is linear; 'step' holds each multiplier until the next declared event.
    Integration lands on every schedule knot and uses exact interval-average
    input power. Conductive/radiative losses use the backward-Euler endpoint.
    Optional initial_temperatures_c provides one explicit initial value per
    node; fixed-temperature boundaries override their matching entries.
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
    frame_interval = settings.get("frame_interval_s")
    if frame_interval is not None:
        frame_interval = _finite(frame_interval, "frame_interval_s", positive=True)
        if duration/frame_interval > 999:
            raise ValueError(f'Playback interval requests at least {math.ceil(duration/frame_interval)+1} stored frames, '+
                             f'above the 1000-frame limit; increase frame_interval_s above {duration/999:.3g} s '+
                             'or shorten duration_s.')
        if "frame_stride" in settings:
            raise ValueError("Choose frame_interval_s or frame_stride, not both.")
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
    output_times = {0., duration}
    if frame_interval is not None:
        # Requested playback times are solve endpoints, never interpolated display values.
        ordered = sorted(timeline)
        for index in range(1, math.ceil(duration/frame_interval)):
            requested = index*frame_interval
            if requested >= duration:
                break
            position = bisect.bisect_left(ordered, requested)
            neighbors = ordered[max(0, position-1):position+1]
            equivalent = next((value for value in neighbors if abs(value-requested) <=
                               8*max(math.ulp(value), math.ulp(requested))), None)
            output_times.add(equivalent if equivalent is not None else requested)
            if equivalent is None:
                bisect.insort(ordered, requested)
        timeline = set(ordered)
    timeline = sorted(timeline)
    steps = len(timeline)-1
    if steps > 10000:
        raise ValueError("Transient including schedule events exceeds 10000 steps; simplify schedules or increase timestep_s.")
    stride = settings.get("frame_stride", max(1, math.ceil(steps/100))) if frame_interval is None else None
    if stride is not None and (isinstance(stride, bool) or not isinstance(stride, int) or stride < 1):
        raise ValueError("frame_stride must be a positive integer.")
    stored_steps={index for index, endpoint in enumerate(timeline[1:],1)
                  if (endpoint in output_times if frame_interval is not None else index % stride == 0)
                  or index == steps or endpoint in events}
    if len(stored_steps)+1 > (1000 if frame_interval is not None else 200):
        raise ValueError(f'{len(stored_steps)+1} stored frames exceed the '+
                         ('1000' if frame_interval is not None else '200')+
                         '-frame limit; increase frame_interval_s or frame_stride, simplify schedules, or shorten duration_s.')
    if (len(stored_steps)+1)*n > 5000000:
        allowed=max(1,5000000//n)
        if allowed < 2:
            raise ValueError(f'{n} nodes exceed five million stored values even for initial and final frames; reduce the mesh.')
        recommended=duration/max(1,allowed-2)
        raise ValueError(f'{len(stored_steps)+1} stored frames × {n} nodes exceed five million values; '+
                         f'increase frame_interval_s to about {recommended*1.1:.3g} s or more '+
                         '(allow more for schedule events), or reduce the mesh.')
    ids = np.array(sorted(fixed), dtype=int)
    free = np.array([i for i in range(n) if i not in fixed], dtype=int)
    if initial_temperatures_c is None:
        temp = np.full(n, initial)
    else:
        temp = vector(initial_temperatures_c, "Initial node temperatures", nonnegative=False).copy()
        if np.any(temp <= -273.15) or np.any(temp > 10000):
            raise ValueError("Initial node temperatures must exceed absolute zero and not exceed 10000 C.")
    for i, v in fixed.items():
        temp[i] = v
    frames = [{"time_s": 0.0, "temperatures_c": temp.tolist()}]
    energy = []
    cache = {}
    linear_boundary = not np.any(emissivity)
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
            rhs = source+contact_rhs+mass*previous+slope*temp-loss
            key = delta if linear_boundary else None
            entry = cache.get(key) if key is not None else None
            if entry is None:
                matrix = laplacian+diags(mass+contact_g+slope, format="csc")
                factor = splu(matrix[free][:, free].tocsc()) if len(free) else None
                coupling = matrix[free][:, ids] if len(ids) else None
                if key is not None:
                    cache[key] = (factor, coupling)
                    if len(cache) > 128:
                        cache.pop(next(iter(cache)))
            else:
                factor, coupling = entry
            if coupling is not None:
                rhs[free] -= coupling@temp[ids]
            candidate = factor.solve(rhs[free]) if len(free) else np.array([])
            if not np.all(np.isfinite(candidate)) or np.any(candidate <= -273.15) or np.any(candidate > 10000):
                raise ValueError("Transient thermal solve diverged.")
            change = max(np.abs(candidate-temp[free]), default=0)
            temp[free] = candidate
            if linear_boundary or change < 1e-7:
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
            "steps": steps, "timestep_s": dt, "frame_interval_s": frame_interval,
            "final_temperatures_c": temp.tolist(),
            "assumptions": [
                "Heat capacities are supplied explicitly by the owning thermal model; the integrator infers no package, barrel, coating or circuit electrothermal properties. Spatial and lumped nodes retain their declared temperature meanings.",
                "Scheduled multipliers use declared " + interpolation + " interpolation and held endpoint values; integration lands on schedule knots and preserves their interval input energy. No operating losses are inferred.",
                "Conductive, convective and radiative loss use backward-Euler endpoint temperatures; time-step convergence must be checked independently. Implicit stability and energy balance do not establish accuracy."]}
