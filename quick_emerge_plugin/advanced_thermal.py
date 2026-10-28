"""Pinned EMerge 3.0.0b9 thermal time-integration compatibility adapter.

The FEM assembly, Dirichlet elimination and output classes remain upstream's.
This fixes only driver bookkeeping: free vs total DOFs, current DataEntry
iteration, and inclusion of the requested terminal time. No installed package
is modified. Later versions use their public run_transient and must pass the
same qualification checks before runtime activation.

API provenance: EMerge commit 446232037d175a596606c6c9ea986e372560566f,
heatconduction_3d.py and simjob.py, Copyright (C) 2025 Robert Fennis.
https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/src/emerge/_emerge/physics/heatconduction/heatconduction_3d.py
SPDX-License-Identifier: GPL-2.0-or-later
"""
import importlib.metadata
import math


def slab_transient_peak(ambient, power_w, area_m2, thickness_m, conductivity,
                        density, specific_heat, time_s):
    """Independent 1D Fourier-series solution: uniform Q, fixed bottom, insulated top."""
    q = power_w/(area_m2*thickness_m)
    alpha = conductivity/(density*specific_heat)
    steady = q*thickness_m**2/(2*conductivity)
    correction = 0.
    for n in range(200):
        lam = (n+.5)*math.pi/thickness_m
        correction += 2*q/(conductivity*thickness_m*lam**3)*((-1)**n)*math.exp(-alpha*lam**2*time_s)
    return ambient+steady-correction


def run_transient(hc, duration, step, nthreads=1):
    import numpy as np
    if importlib.metadata.version('emerge') != '3.0.0b9':
        data = hc.run_transient(duration, step, stepping_algorithm='BackwardEuler', nthreads=nthreads)
        frames = list(data.field.iter())
        times = [float(frame.time) for frame in frames]
        if not times or not math.isclose(times[-1], duration, rel_tol=0., abs_tol=1e-9):
            raise RuntimeError('Upstream transient did not produce the requested terminal time; runtime qualification cannot accept it')
        return data, dict(method='upstream BackwardEuler', requested_terminal_time_s=duration,
                          time_s=times, peak_k=[float(np.max(frame.T)) for frame in frames], step_s=step)
    from emerge._emerge.solver import SolveReport
    hc._check_meshed()
    hc._initialize_field()
    hc._initialize_bc_data()
    hc._check_physics()
    hc._generate_material_assignment()
    job, materials, initial = hc.assembler.assemble_hc_matrix(
        hc.basis, hc.mat_assy, hc.bc.boundary_conditions, hc.T_initial_K, transient=True)
    steps = int(math.ceil(duration/step))
    dt = duration/steps  # exact terminal time, no overshoot or truncated last interval
    lhs, rhs_matrix, source, ids, aux = job.get_ABb(dt, 'BackwardEuler')
    temperature = np.asarray(initial)[job.i_free].reshape(-1)
    times = np.linspace(0, duration, steps+1)
    peak = [float(np.max(initial))]
    final_job = None
    try:
        for time_s in times[1:]:
            rhs = rhs_matrix @ temperature + source.reshape(-1)
            solution, report = hc.solveroutine.solve(lhs, rhs, ids, id=job.id,
                                                     direct=True, nthreads=nthreads)
            temperature = np.asarray(solution).reshape(-1)
            if temperature.size != job.n_free or not np.all(np.isfinite(temperature)):
                raise ValueError('Transient solver returned invalid free-DOF temperatures')
            report.add(**aux)
            final_job = job.submit_copy(temperature, report)
            peak.append(float(np.max(final_job.solution)))
    finally:
        hc.solveroutine.reset()
    hc.data.setreport(final_job.reports, **hc._params)
    hc._post_process_transient([final_job], np.asarray([duration]), materials)
    return hc.data, dict(method='BackwardEuler; EMerge 3.0.0b9 driver compatibility adapter',
                         time_s=times.tolist(), peak_k=peak, step_s=dt,
                         requested_terminal_time_s=duration)
