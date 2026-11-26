"""Couple 3D copper conductivity to the saved board's layer thermal model."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import numpy as np

from .electrothermal import _number, ElectrothermalError
from .electrothermal_service import validate_feedback_inputs
from .full3d import solve_volume
from wayricad_runtime.thermal_multilayer import (
    DistributedHeatSource, prepare_distributed_sources, solve_multilayer_thermal,
)


def _thermal_projection(thermal_geometry, settings, centroids):
    """Assign each copper centroid to an XY cell and one or two adjacent layers."""
    from matplotlib.path import Path

    layers = thermal_geometry['layers']
    z = np.array([layer['z_mm'] for layer in layers])
    half = np.array([layer['thickness_mm'] for layer in layers]) / 2
    slab_lo, slab_hi = z - half, z + half
    if len(z) < 2 or np.any(slab_lo[1:] <= slab_hi[:-1]):
        raise ElectrothermalError('source_mismatch', 'Thermal copper stackup needs distinct, ordered layers.')
    if np.any(centroids[:, 2] < slab_lo[0] - 1e-6) or np.any(centroids[:, 2] > slab_hi[-1] + 1e-6):
        raise ElectrothermalError('source_mismatch', '3D copper lies outside the saved thermal stackup.')

    def contains(ring):
        return Path([*ring, ring[0]], closed=True).contains_points(centroids[:, :2])

    inside = np.zeros(len(centroids), dtype=bool)
    for outline in thermal_geometry['outline']:
        region = contains(outline['outer_mm'])
        for hole in outline.get('holes_mm', []):
            region &= ~contains(hole)
        inside |= region
    if not inside.all():
        raise ElectrothermalError('missing_mapping', '3D copper has a powered cell centroid outside the verified board material.')

    top = np.clip(np.searchsorted(slab_lo, centroids[:, 2], side='right') - 1, 0, len(z) - 1)
    bottom = np.minimum(top + 1, len(z) - 1)
    gap = np.where(top == bottom, 1, slab_lo[bottom] - slab_hi[top])
    fraction = np.clip((centroids[:, 2] - slab_hi[top]) / gap, 0, 1)
    fraction[top == bottom] = 0

    xmin, ymin, xmax, ymax = thermal_geometry['bbox_mm']
    width, height = xmax - xmin, ymax - ymin
    grid = settings.get('grid_cells_long_axis', 48)
    if (width <= 0 or height <= 0 or isinstance(grid, bool)
            or not isinstance(grid, int) or not 24 <= grid <= 80):
        raise ValueError('Invalid board extent or thermal grid resolution.')
    nx, ny = max(2, round(grid * width / max(width, height))), max(2, round(grid * height / max(width, height)))
    dx, dy = width / nx, height / ny
    ix = np.clip(np.floor((centroids[:, 0] - xmin) / dx).astype(int), 0, nx - 1)
    iy = np.clip(np.floor((centroids[:, 1] - ymin) / dy).astype(int), 0, ny - 1)
    xy = iy * nx + ix
    blend = fraction > 0
    bins, inverse = np.unique(np.concatenate((top * nx * ny + xy, bottom[blend] * nx * ny + xy[blend])),
                              return_inverse=True)
    sources = []
    for code in bins:
        layer_index, xy_index = divmod(int(code), nx * ny)
        j, i = divmod(xy_index, nx)
        # The shared kernel calls its point-support primitive "via". Here it
        # represents integrated volume heat in one board thermal cell.
        sources.append(DistributedHeatSource(
            f'volume-bin-{code}', 'via', 0., layers[layer_index]['id'],
            point_mm=[xmin + (i + .5) * dx, ymin + (j + .5) * dy]))
    support = prepare_distributed_sources(thermal_geometry, settings, sources)
    base_bins, split_bins = inverse[:len(xy)], inverse[len(xy):]
    return sources, support, base_bins, split_bins, fraction, blend


def solve_volume_feedback(mesh, source_nodes, sink_nodes, thermal_geometry, feedback,
                          *, source_voltage, sink_current=1., options=None, sinks=None, source_current_limit=None):
    """Solve steady feedback, with separate cold results if hot coupling stops."""
    if not isinstance(feedback, Mapping):
        raise ValueError('3D Joule feedback expects thermal settings and coupling inputs.')
    settings = feedback.get('thermal_settings')
    coupling = feedback.get('coupling')
    assumptions = feedback.get('assumptions', [])
    if not isinstance(assumptions, (list, tuple)) or any(not isinstance(item, str) for item in assumptions):
        raise ValueError('3D Joule assumptions must be a list of descriptions.')
    if not isinstance(settings, Mapping) or not isinstance(coupling, Mapping):
        raise ValueError('3D Joule feedback needs thermal_settings and coupling objects.')
    electrical_options = dict(options or {})
    electrical_options.setdefault('resistivity_ohm_m', 1.724e-8)
    electrical_options.setdefault('temperature_coefficient', .00393)
    validate_feedback_inputs(dict(thermal_settings=settings, coupling=coupling,
                                 electrical={'options': electrical_options}))
    ambient = settings['ambient_c']
    if not np.isclose(settings['via_plating_mm'], mesh['plating_mm'], rtol=1e-9, atol=1e-12):
        raise ElectrothermalError('source_mismatch', 'Use the same via plating for 3D copper and board cooling.')
    minimum, maximum = coupling['material_temperature_range_c']
    if not minimum <= ambient <= maximum:
        raise ValueError('Ambient must be inside the material temperature range.')
    cap = coupling['temperature_cap_c']
    relaxation = _number(coupling.get('relaxation', .5), 'Relaxation', 1e-6, 1)
    t_tol = _number(coupling.get('temperature_tolerance_c', .01), 'Temperature tolerance', 1e-12)
    p_tol = _number(coupling.get('loss_relative_tolerance', 1e-5), 'Relative loss tolerance', 0)
    p_abs = _number(coupling.get('loss_absolute_tolerance_w', 1e-8), 'Absolute loss tolerance', 0)
    iterations = coupling.get('max_iterations', 60)
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 1000:
        raise ValueError('max_iterations must be an integer from 1 to 1000.')
    if not thermal_geometry.get('outline') or thermal_geometry.get('outline_status') != 'valid':
        raise ValueError('A verified closed Edge.Cuts outline is required for 3D Joule feedback.')

    electrical_options['temperature_c'] = ambient

    def electrical(temperatures=None):
        return solve_volume(mesh, source_nodes, sink_nodes, source_voltage, sink_current,
                            electrical_options, element_temperature_c=temperatures,
                            sinks=sinks, source_current_limit=source_current_limit)

    cold = electrical()
    active = np.array([power is not None for power in cold['cell_power_W']])
    centroids = np.asarray(cold['cell_centroid_mm'])[active]
    sources, support, base_bins, split_bins, fraction, blend = _thermal_projection(
        thermal_geometry, settings, centroids)
    temperatures = np.full(len(active), float(ambient))
    thermal_result = {'environment': settings.get('environment', 'air'), 'ambient_c': ambient, 'components': []}
    history, previous_loss = [], None
    status = 'iteration_limit'
    diagnostic = 'Coupling iteration limit reached. Review cooling, load and mesh settings.'
    output = cold
    thermal_assembly = {}
    for index in range(1, iterations + 1):
        electric = cold if index == 1 else electrical(temperatures)
        watts = np.asarray([power for power in electric['cell_power_W'] if power is not None])
        # Use the same weights for heat deposition and temperature sampling.
        # Aggregating by cell prevents the thermal system from growing with the
        # tetrahedron count and preserves total power even through via transfers.
        grouped = np.bincount(base_bins, weights=watts * (1 - fraction), minlength=len(sources))
        grouped += np.bincount(split_bins, weights=watts[blend] * fraction[blend], minlength=len(sources))
        loss = electric['total_power_W']
        mapped = float(grouped.sum())
        transfer_residual = mapped - loss
        if abs(transfer_residual) > max(1e-12, abs(loss) * 1e-10):
            raise ElectrothermalError('transfer_imbalance', '3D copper heat transfer did not conserve watts.')
        loads = [replace(source, power_w=float(power)) for source, power in zip(sources, grouped)]
        board = solve_multilayer_thermal(thermal_geometry, {'components': []}, thermal_result, settings,
                                         distributed_sources=loads, prepared_sources=support,
                                         _assembly=thermal_assembly)
        if board['status'] != 'converged':
            raise ElectrothermalError('thermal_imbalance', 'Thermal boundary heat balance failed.')
        samples = np.array([row['temperature_c'] for row in board['distributed_sources']])
        target = samples[base_bins] * (1 - fraction)
        target[blend] += samples[split_bins] * fraction[blend]
        residual = float(np.max(np.abs(target - temperatures[active])))
        change = None if previous_loss is None else abs(loss - previous_loss)
        hottest = max(layer['sampled_max_c'] for layer in board['layers'])
        coolest = min(layer['sampled_min_c'] for layer in board['layers'])
        history.append(dict(iteration=index, temperature_residual_c=residual, loss_w=loss,
                            loss_change_w=change, mapped_loss_w=mapped, transfer_residual_w=transfer_residual,
                            maximum_c=hottest, minimum_c=coolest,
                            thermal_balance_residual_w=board['heat_balance']['residual_w'],
                            electrical_energy_relative_error=electric['energy_relative_error']))
        if coolest < minimum or hottest > maximum:
            status, diagnostic = ('material_range_exceeded',
                                  'Board temperatures left the declared copper material temperature range.')
            break
        if hottest > cap:
            status, diagnostic = ('temperature_cap',
                                  'Board temperatures exceeded the configured stop temperature.')
            break
        if change is not None and residual <= t_tol and change <= p_abs + p_tol * abs(loss):
            status = 'converged'
            diagnostic = 'Copper temperature, loss and the board heat balance satisfy the declared tolerances.'
            output = electric
            break
        temperatures[active] += relaxation * (target - temperatures[active])
        previous_loss = loss

    converged = status == 'converged'
    output['solution_basis'] = 'coupled_steady' if converged else 'cold_baseline'
    output['joule_feedback'] = dict(
        status=status, converged=converged, diagnostic=diagnostic, peak_temperature_c=hottest,
        cold={key: cold[key] for key in ('voltage_drop_V', 'sink_voltage_V', 'drop_over_current_ohm', 'total_power_W', 'sinks', 'feasibility')},
        history=history, iterations=len(history), heat_balance=board['heat_balance'], thermal_settings=dict(settings),
        coupling=dict(coupling), thermal_model=board['model'],
        assumptions=[*assumptions,
                     'The electrical solve uses tetrahedral copper; board cooling uses a layer-resolved thermal grid.',
                     'Centroid-based heat mapping conserves watts; interlayer copper shares heat between adjacent slabs.',
                     'Only analyzed copper I²R loss is deposited. Delivered load power and junction temperatures are excluded.'])
    return output
