'''Net ownership for the board viewport, including older saved results.'''

def analyzed_nets(bundle):
    geometry = bundle.get('geometry') or bundle.get('mesh', {}).get('geometry', {})
    return geometry.get('nets') or [net for net in (geometry.get('net') or bundle.get('request', {}).get('net'),) if net]


def mesh_net_labels(bundle):
    import numpy as np

    mesh = bundle.get('mesh', {})
    triangles = mesh.get('triangles', [])
    nets = analyzed_nets(bundle)
    if len(nets) <= 1:
        return np.full(len(triangles), nets[0] if nets else '', dtype=object)
    labels = np.full(len(triangles), '', dtype=object)
    for domain in mesh.get('display_net_domains', []):
        labels[domain['first_cell']:domain['end_cell']] = domain['net']
    if 'display_net_domains' not in mesh and mesh.get('series_domains'):
        vertices = np.asarray(triangles, dtype=int)
        if vertices.size:
            low, high = vertices.min(axis=1), vertices.max(axis=1)
            for domain in mesh['series_domains']:
                labels[(low >= domain['start']) & (high < domain['end'])] = domain['net']
    return labels
