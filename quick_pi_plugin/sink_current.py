"""Independent prescribed-load updates on an existing, fixed copper mesh."""
import copy
import math

from .live_current import LiveCurrentError, live_current_eligibility


class SinkCurrentModel:
    """Retain topology and re-solve only electrical fields; never remesh a PCB.

    The caller owns saved-source and UI generation checks. Each update is a
    fresh fixed-temperature solve because changing one load redistributes
    current and quadratic losses throughout shared copper.
    """
    def __init__(self, bundle):
        supported, reason = live_current_eligibility(bundle)
        if not supported:
            raise LiveCurrentError(reason)
        from .service import sink_requests
        from .terminals import resolve_units
        self.base = bundle
        self.request = copy.deepcopy(bundle['request'])
        self.geometry = bundle.get('geometry') or bundle['mesh'].get('geometry', {})
        self.specs = sink_requests(self.request)
        _, self.source, self.electrodes, self.units = resolve_units(
            self.request, self.geometry, bundle['mesh'], self.specs)
        self.currents = [float(row['current_A']) for row in self.electrodes]

    def update(self, currents):
        """Solve a positive current per original sink, retaining all other inputs."""
        if not isinstance(currents, (list, tuple)) or len(currents) != len(self.specs):
            raise LiveCurrentError('Supply one current for each original sink.')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or v <= 0 for v in currents):
            raise LiveCurrentError('Each sink current must be finite and positive.')
        from .solver import solve
        from .service import _solver_mesh_budgets
        request = copy.deepcopy(self.request)
        request.pop('sink_terminal', None)
        request.pop('sink_current', None)
        request.pop('sink_min_voltage', None)
        request.pop('sink_max_voltage', None)
        request['sinks'] = [dict(row, current_A=value) for row, value in zip(self.specs, currents)]
        sinks = [dict(row, current_A=value) for row, value in zip(self.electrodes, currents)]
        result = solve(self.base['mesh'], self.source, sinks=sinks,
                       source_voltage=request.get('source_voltage', 1.),
                       source_current_limit=request.get('source_current_limit'),
                       options=request.get('options'), **_solver_mesh_budgets(request))
        result['live_current'] = {
            'basis': 'independent prescribed sink currents; fixed-mesh electrical re-solve',
            'currents_A': list(currents),
            'notice': 'No remesh; shared copper current and I²R losses are recomputed.'}
        units = copy.deepcopy(self.units)
        for row, value in zip(units['loads'], currents):
            row['current_A'] = value
        output = dict(self.base, request=request, result=result, terminal_units=units)
        # A convergence result for the old load vector cannot qualify new peaks.
        output.pop('convergence', None)
        return output
