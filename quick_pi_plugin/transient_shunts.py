"""Individual passive shunt branches for the lumped transient model.

Branch currents j charge individual capacitors v; A maps branches to load
nodes and i=A j+d are feed currents. Between constant-demand events:
    M j' + R j + v = A.T (Vs - Q d - P d'), C v' = j
    M = diag(ESL) + A.T P A; R = diag(ESR) + A.T Q A
P/Q contain path and shared-source inductance/resistance. No bank averaging
is used in these equations. Ideal constraints are handled in topology-derived
nullspaces; event projection preserves every physical inductor current and
capacitor voltage, or rejects a step requiring an impulse.
"""
from __future__ import annotations

import math


def _nullspace(np, rows, count):
    if not rows:
        return np.eye(count)
    matrix = np.array(rows, dtype=float)
    _, singular, vh = np.linalg.svd(matrix, full_matrices=True)
    rank = int(np.sum(singular > 32 * np.finfo(float).eps * max(matrix.shape) * singular[0]))
    return vh[rank:].T


def build(parameters, np, cho_factor, cho_solve):
    from .transient import _factor, TransientError
    loads = parameters['loads']; count = len(loads)
    branches = []
    owners = []
    for index, row in enumerate(loads):
        bank = row.get('shunt_capacitors')
        if bank is None:
            bank = [dict(id='aggregate', capacitance_F=row['capacitance_F'],
                         esr_ohm=row['esr_ohm'], esl_H=0.)]
        branches.extend(bank); owners.extend([index] * len(bank))
    size = len(branches)
    a = np.zeros((count, size)); a[owners, np.arange(size)] = 1
    c = np.array([row['capacitance_F'] for row in branches])
    esr = np.array([row['esr_ohm'] for row in branches])
    esl = np.array([row['esl_H'] for row in branches])
    path_r = np.array([row['path_resistance_ohm'] for row in loads])
    path_l = np.array([row['path_inductance_H'] for row in loads])
    p = np.diag(path_l) + parameters['source_inductance_H'] * np.ones((count, count))
    q = np.diag(path_r) + parameters['source_resistance_ohm'] * np.ones((count, count))
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        m = np.diag(esl) + a.T @ p @ a
        r = np.diag(esr) + a.T @ q @ a
        inverse_c = 1 / c
    if not all(np.isfinite(v).all() for v in (m, r, inverse_c)):
        raise TransientError('Explicit shunt R/L/C parameters exceed a finite numerical range.')
    # Unweighted incidence constraints identify exact topology; tiny but
    # positive inductors are never rounded to zero by an eigenvalue threshold.
    identity = np.eye(size)
    magnetic_rows = [identity[k] for k in np.flatnonzero(esl > 0)]
    demand_rows = [np.zeros(count) for _ in magnetic_rows]
    for k in np.flatnonzero(path_l > 0):
        magnetic_rows.append(a[k]); demand_rows.append(np.eye(count)[k])
    if parameters['source_inductance_H'] > 0:
        magnetic_rows.append(np.ones(size)); demand_rows.append(np.ones(count))
    n = _nullspace(np, magnetic_rows, size)
    resistance_rows = [identity[k] for k in np.flatnonzero(esr > 0)]
    resistance_rows.extend(a[k] for k in np.flatnonzero(path_r > 0))
    resistance_rows.append(np.ones(size))  # source R is strictly positive
    z = _nullspace(np, magnetic_rows + resistance_rows, size)
    projection = charge_projection = None
    if n.shape[1]:
        reduced = n.T @ r @ n
        if z.shape[1]:
            coordinates = n.T @ z
            reduced += float(np.max(np.diag(r))) * coordinates @ coordinates.T
            charge_projection = _factor(np, cho_factor, z.T @ (inverse_c[:, None] * z))
        projection = _factor(np, cho_factor, reduced)
    # Basis of magnetic range, used only to reconstruct instantaneous voltages.
    h = _nullspace(np, list(n.T), size)
    magnetic_factor = _factor(np, cho_factor, h.T @ m @ h) if h.shape[1] else None
    return dict(bank=True, a=a, branches=branches, owners=owners, capacitance=c,
                inverse_c=inverse_c, esr=esr, esl=esl, path_r=path_r, path_l=path_l,
                p=p, q=q, inductance=m, resistance=r, null_l=n, null_both=z,
                projection=projection, charge_projection=charge_projection,
                magnetic_rows=np.array(magnetic_rows).reshape((-1, size)),
                demand_rows=np.array(demand_rows).reshape((-1, count)),
                magnetic_basis=h, magnetic_factor=magnetic_factor,
                cho_solve=cho_solve)


def forcing(parameters, model, demand, demand_rate=None):
    value = parameters['source_voltage_V'] - model['q'] @ demand
    if demand_rate is not None:
        value = value - model['p'] @ demand_rate
    return model['a'].T @ value


def event_current(parameters, model, current, capacitor, demand, previous_demand, np, cho_solve, demand_rate=None):
    from .transient import _solve, TransientError
    if previous_demand is None:
        previous_demand=demand
    updated = current.copy()
    e = model['magnetic_rows']
    if e.shape[0]:
        right = -model['demand_rows'] @ (demand - previous_demand)
        change = np.linalg.lstsq(e, right, rcond=None)[0]
        tolerance = 1e-11 * max(float(np.max(np.abs(right))), 1e-300)
        if float(np.max(np.abs(e @ change - right))) > tolerance:
            raise TransientError('This ideal load step requires impulsive voltage: feed and shunt ESL currents cannot all remain continuous. Set a positive rise_time_s for a finite current ramp, or revise the explicit inductances.')
        updated += change
    n = model['null_l']; z = model['null_both']
    if n.shape[1]:
        right = forcing(parameters, model, demand, demand_rate) - capacitor - model['resistance'] @ updated
        if z.shape[1]:
            right -= z @ (z.T @ right)
        updated += n @ _solve(np, cho_solve, model['projection'], n.T @ right)
        if z.shape[1]:
            updated -= z @ _solve(np, cho_solve, model['charge_projection'],
                                  z.T @ (model['inverse_c'] * updated))
    return updated


def quantities(parameters, model, current, capacitor, demand, np, demand_rate=None):
    from .transient import _solve
    a = model['a']; feed = a @ current + demand
    h = model['magnetic_basis']
    derivative = np.zeros_like(current)
    if h.shape[1]:
        residual = forcing(parameters, model, demand, demand_rate) - model['resistance'] @ current - capacitor
        derivative = h @ _solve(np, model['cho_solve'], model['magnetic_factor'], h.T @ residual)
    feed_derivative = a @ derivative
    if demand_rate is not None:
        feed_derivative += demand_rate
    voltage = parameters['source_voltage_V'] - model['q'] @ feed - model['p'] @ feed_derivative
    source_current = float(feed.sum())
    source_voltage = (parameters['source_voltage_V'] - parameters['source_resistance_ohm'] * source_current
                      - parameters['source_inductance_H'] * float(feed_derivative.sum()))
    path_loss = model['path_r'] * feed ** 2
    branch_loss = model['esr'] * current ** 2
    source_loss = parameters['source_resistance_ohm'] * source_current ** 2
    branch_stored = .5 * (model['capacitance'] * capacitor ** 2 + model['esl'] * current ** 2)
    stored = float(.5 * feed @ model['p'] @ feed + branch_stored.sum())
    return dict(current=feed, capacitor=(a @ (model['capacitance'] * capacitor)) / (a @ model['capacitance']),
                demand=demand.copy(), voltage=voltage, source_current=source_current,
                source_voltage=source_voltage, path_loss=path_loss, esr_loss=a @ branch_loss,
                source_loss=source_loss, loss=float(source_loss+path_loss.sum()+branch_loss.sum()),
                stored=stored, source_power=parameters['source_voltage_V']*source_current,
                load_power=voltage*demand, branch_current=current.copy(), branch_capacitor=capacitor.copy(),
                branch_loss=branch_loss, branch_stored=branch_stored)


def advance(parameters, model, current, capacitor, demand, step, cache, np, cho_factor, cho_solve,
            previous_demand=None):
    from .transient import _factor, _solve, TransientError
    m = model['inductance']; r = model['resistance']; c = model['capacitance']
    if previous_demand is None:
        previous_demand=demand
    # The load is exactly linear inside each event-bounded interval. Use its
    # actual increment in BE's inductor equation and energy ledger. Separately
    # recorded samples use the prescribed one-sided slope at each boundary.
    interval_rate=(demand-previous_demand)/step
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        if step not in cache:
            cache[step] = _factor(np, cho_factor, m / step + r + np.diag(step * model['inverse_c']))
            if len(cache) > 256:
                cache.pop(next(iter(cache)))
        updated = _solve(np, cho_solve, cache[step], m @ current / step + forcing(parameters, model, demand, interval_rate) - capacitor)
        updated_v = capacitor + step * model['inverse_c'] * updated
    values = quantities(parameters, model, updated, updated_v, demand, np, interval_rate)
    di = updated-current; dv = updated_v-capacitor
    old_feed = model['a'] @ current+previous_demand
    new_feed = values['current']; delta_feed = new_feed-old_feed
    delta_energy = float(.5 * delta_feed @ model['p'] @ (new_feed+old_feed)
                         + .5 * np.dot(model['esl'] * di, updated+current)
                         + .5 * np.dot(c * dv, updated_v+capacitor))
    damping = float(.5 * delta_feed @ model['p'] @ delta_feed + .5 * np.dot(model['esl'],di**2)
                    + .5 * np.dot(c, dv**2))
    supplied = step * values['source_power']; load_energy = step * float(values['load_power'].sum())
    loss_energy = step * values['loss']
    charge_residual = c*dv-step*updated
    kvl = m @ di/step+r @ updated+updated_v-forcing(parameters, model, demand, interval_rate)
    ledger = dict(source_energy_J=supplied, load_energy_J=load_energy, resistive_loss_energy_J=loss_energy,
                  backward_euler_numerical_dissipation_J=damping,
                  energy_residual_J=delta_energy-supplied+load_energy+loss_energy+damping,
                  delta_stored_energy_J=delta_energy,
                  max_charge_residual_C=float(np.max(np.abs(charge_residual))),
                  max_kvl_residual_V=float(np.max(np.abs(kvl))),
                  energy_scale=abs(delta_energy)+abs(supplied)+abs(load_energy)+abs(loss_energy)+damping,
                  # Include transported load charge as the legacy ledger does;
                  # at DC the true capacitor current is zero, and normalizing
                  # solely by its roundoff would report a false 100% error.
                  charge_scale=float(np.sum(np.abs(c*dv)+step*(np.abs(updated)
                                     + model['a'].T @ (np.abs(new_feed)+np.abs(demand))))),
                  charge_error=float(np.sum(np.abs(charge_residual))))
    if not all(np.isfinite(value).all() for value in (*values.values(), *ledger.values())):
        raise TransientError('Shunt branch state/energy exceeded a finite numerical range.')
    return updated, updated_v, values, ledger


def demand_at(parameters, time, np, *, after):
    """Exact piecewise-linear prescribed demands and one-sided slopes."""
    values=[];rates=[]
    for row in parameters['loads']:
        start=row['step_time_s']; rise=row.get('rise_time_s',0.)
        initial=row['initial_current_A']; final=row['step_current_A']
        if not rise:
            values.append(final if time>start or (after and time==start) else initial)
            rates.append(0.)
        else:
            end=start+rise
            values.append(initial if time<=start else final if time>=end else initial+(final-initial)*(time-start)/rise)
            active=(start<time<end) or (after and time==start) or (not after and time==end)
            rates.append((final-initial)/rise if active else 0.)
    return np.array(values),np.array(rates)


def integrate(parameters, model, timeline, events, cancel, np, cho_factor, cho_solve):
    """Integrate exact step/ramp boundaries while retaining legacy result keys."""
    from .transient import TransientError
    demand=np.array([row['initial_current_A'] for row in parameters['loads']])
    rate=np.zeros_like(demand)
    current=np.zeros(len(model['branches']))
    capacitor=model['a'].T@(parameters['source_voltage_V']-model['q']@demand)
    times=[];phases=[];samples=[];cache={}
    totals=dict(source_energy_J=0.,load_energy_J=0.,resistive_loss_energy_J=0.,
                backward_euler_numerical_dissipation_J=0.,energy_residual_J=0.,
                max_charge_residual_C=0.,max_kvl_residual_V=0.)
    energy_scale=charge_scale=charge_error=absolute_energy_error=0.

    def cancelled():
        if cancel and cancel():
            raise InterruptedError('Quick PI transient cancelled. No board files were changed.')

    def record(time,phase):
        values=quantities(parameters,model,current,capacitor,demand,np,rate)
        if not all(np.isfinite(value).all() for value in values.values()):
            raise TransientError('Transient output exceeded a finite numerical range.')
        times.append(time);phases.append(phase);samples.append(values)

    def event(time):
        nonlocal current,demand,rate
        previous=demand
        demand,rate=demand_at(parameters,time,np,after=True)
        current=event_current(parameters,model,current,capacitor,demand,previous,np,cho_solve,rate)
        record(time,'step_after')

    cancelled();record(0.,'initial');initial=samples[0]
    if 0. in events:
        event(0.)
    for previous,time in zip(timeline,timeline[1:]):
        cancelled();step=time-previous
        if step<=0:
            raise TransientError('Event times cannot be distinguished at floating-point resolution.')
        previous_demand=demand
        demand,rate=demand_at(parameters,time,np,after=False)
        current,capacitor,_,ledger=advance(parameters,model,current,capacitor,demand,step,cache,np,
                                          cho_factor,cho_solve,previous_demand)
        absolute_energy_error+=abs(ledger['energy_residual_J'])
        for key in ('source_energy_J','load_energy_J','resistive_loss_energy_J',
                    'backward_euler_numerical_dissipation_J','energy_residual_J'):
            totals[key]+=ledger[key]
        for key in ('max_charge_residual_C','max_kvl_residual_V'):
            totals[key]=max(totals[key],ledger[key])
        energy_scale+=ledger['energy_scale'];charge_scale+=ledger['charge_scale'];charge_error+=ledger['charge_error']
        record(time,'step_before' if time in events else 'sample')
        if time in events:
            event(time)
    totals.update(energy_relative_error=absolute_energy_error/max(energy_scale,1e-300),
                  charge_relative_error=charge_error/max(charge_scale,1e-300),
                  initial_stored_energy_J=initial['stored'],final_stored_energy_J=samples[-1]['stored'],
                  intervals=len(timeline)-1,samples=len(samples),
                  max_interval_s=max(right-left for left,right in zip(timeline,timeline[1:])))
    if not all(math.isfinite(value) for value in totals.values()):
        raise TransientError('Transient conservation checks exceeded a finite numerical range.')
    totals['balance_status']='PASSED' if max(totals['energy_relative_error'],totals['charge_relative_error'])<=1e-8 else 'FAILED'
    return times,phases,samples,totals


def recommend_step(study):
    """Same finite descriptor-mode advice contract as legacy transient inputs."""
    from .transient import _request, _factor, _solve, MAX_COARSE_INTERVALS
    import numpy as np
    from scipy.linalg import cho_factor, cho_solve, eigvals, solve_triangular
    parameters = _request(dict(study, step_s=float(study['duration_s'])/1000))
    model = build(parameters, np, cho_factor, cho_solve)
    size = len(model['capacitance']); h=model['magnetic_basis']; n=model['null_l']; z=model['null_both']
    w = _nullspace(np, list(z.T), size)
    # Eliminate algebraic currents and ideal capacitor constraints before mode
    # analysis. QZ on the singular descriptor can turn infinite constraint
    # eigenvalues into enormous finite rates when an ideal cap is split.
    magnetic_count=h.shape[1]; voltage_count=w.shape[1]
    jmap=np.column_stack((h,np.zeros((size,voltage_count))))
    vmap=np.column_stack((np.zeros((size,magnetic_count)),w))
    if n.shape[1]:
        right=-model['resistance']@jmap-vmap
        if z.shape[1]:
            right-=z@(z.T@right)
        jmap+=n@np.column_stack([_solve(np,cho_solve,model['projection'],column) for column in (n.T@right).T])
        if z.shape[1]:
            right=z.T@(model['inverse_c'][:,None]*jmap)
            jmap-=z@np.column_stack([_solve(np,cho_solve,model['charge_projection'],column) for column in right.T])
    descriptor=np.block([[h.T@model['inductance']@h,np.zeros((magnetic_count,voltage_count))],
                         [np.zeros((voltage_count,magnetic_count)),w.T@(model['capacitance'][:,None]*w)]])
    dynamics=np.vstack((h.T@(-model['resistance']@jmap-vmap),w.T@jmap))
    decomposition,scale=_factor(np,cho_factor,descriptor)
    lower=np.tril(decomposition[0])
    balanced=dynamics*scale[:,None]*scale[None,:]
    balanced=solve_triangular(lower,balanced,lower=True)
    balanced=solve_triangular(lower,balanced.T,lower=True).T
    modes = eigvals(balanced)
    rates = [abs(value) for value in modes if np.isfinite(value) and abs(value)>0]
    step = min(parameters['duration_s']/1000, 1/(20*max(rates))) if rates else parameters['duration_s']/1000
    rises=[row['rise_time_s'] for row in parameters['loads'] if row.get('rise_time_s',0)>0]
    if rises:
        step=min(step,min(rises)/20)
    intervals = math.ceil(parameters['duration_s']/step)
    return dict(step_s=step, intervals=intervals, within_budget=intervals<=MAX_COARSE_INTERVALS,
                maximum_intervals=MAX_COARSE_INTERVALS,
                note='Starting suggestion from individual shunt R/L/C modes and at least 20 intervals per prescribed ramp; review half-step convergence. Zero-rise steps are ideal discontinuities.')
