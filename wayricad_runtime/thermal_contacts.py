"""Compatible fixed-temperature contacts and conservative flux accounting."""
import math


def add_fixed_contact(fixed, node, temperature):
    if node in fixed and not math.isclose(fixed[node], temperature, rel_tol=0, abs_tol=1e-9):
        raise ValueError(
            'Conflicting fixture temperatures map to one thermal cell '
            f'({fixed[node]:g} and {temperature:g} C). Refine the mesh or correct the contacts.')
    fixed[node] = temperature


def resolve_mount_fluxes(mounts, temperatures, residual):
    """Count a shared Dirichlet reaction once; individual shares are unknown."""
    groups = {}
    total = []
    for mount in mounts:
        node = mount.pop('node_index')
        if mount['contact_r_k_w'] == 0:
            groups.setdefault(node, []).append(mount)
        else:
            flux = float((temperatures[node]-mount['temperature_c'])/mount['contact_r_k_w'])
            mount['heat_flux_w'] = flux
            total.append(flux)
    for node, group in groups.items():
        flux = float(-residual[node])
        total.append(flux)
        for mount in group:
            mount['heat_flux_w'] = flux if len(group) == 1 else None
            if len(group) > 1:
                mount['shared_contact_ids'] = [item['id'] for item in group]
                mount['shared_cell_heat_flux_w'] = flux
                mount['flux_note'] = 'Shared mesh-cell reaction; individual contact heat flows are unresolved.'
    return math.fsum(total)
