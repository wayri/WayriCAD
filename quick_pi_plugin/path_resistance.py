"""Current-normalized DC potential drop sampled along exact saved track chains."""
from bisect import bisect_left
import math

from .series_path_diagram import copper_lengths
from .view_scope import mesh_net_labels


NOTICE = ("Each dot is (source voltage − solved copper potential) / total solved source current. "
          "Parallel paths and other loads affect this profile. It describes the selected operating "
          "point; individual trace or via resistance requires its own current. Distance follows "
          "saved planar centerlines. Zone travel and via barrel lengths are excluded.")


class SheetProbe:
    """Spatial index of the selected net and layer; evaluate only containing P1 cells."""
    def __init__(self, xy, triangles, values):
        import numpy as np
        from scipy.spatial import cKDTree

        self.groups = []
        if not len(triangles):
            return
        vertices = xy[triangles]
        centers = vertices.mean(axis=1)
        radius = np.linalg.norm(vertices - centers[:, None], axis=2).max(axis=1)
        # Size bands keep a single large plane triangle from inflating every search.
        bands = np.frexp(radius)[1]
        for band in np.unique(bands):
            rows = (bands == band) & (radius > 0)
            if np.any(rows):
                self.groups.append((cKDTree(centers[rows]), float(radius[rows].max()),
                                    vertices[rows], values[triangles[rows]]))

    def potential(self, x, y):
        import numpy as np

        result = []
        for tree, radius, vertices, values in self.groups:
            hits = tree.query_ball_point((x,y), radius * (1+1e-11) + 1e-10)
            if not hits:
                continue
            abc = vertices[hits]
            a = abc[:,0]; u = abc[:,1]-a; v = abc[:,2]-a; q = (x,y)-a
            det = u[:,0]*v[:,1]-u[:,1]*v[:,0]
            with np.errstate(divide='ignore', invalid='ignore'):
                b = (q[:,0]*v[:,1]-q[:,1]*v[:,0])/det
                c = (u[:,0]*q[:,1]-u[:,1]*q[:,0])/det
            weights = np.stack((1-b-c,b,c),axis=1)
            inside = np.isfinite(weights).all(axis=1) & (weights >= -1e-9).all(axis=1)
            if inside.any():
                result.extend((weights[inside]*values[hits][inside]).sum(axis=1))
        if not result or not all(math.isfinite(value) for value in result):
            return None
        if not math.isclose(min(result),max(result),rel_tol=1e-12,abs_tol=1e-12):
            return None  # Ambiguous overlapping sheets cannot supply one potential.
        return float(result[0])


def _position(track, start, end, fraction):
    """Use the saved through-point to follow the sweep in either direction."""
    if fraction <= 1e-12:
        return start
    if fraction >= 1-1e-12:
        return end
    mid = track.get('mid_mm')
    if mid is None:
        if track.get('kind') == 'arc' or not math.isclose(math.dist(start,end),
                track['length_mm'], rel_tol=1e-6, abs_tol=2e-6):
            return None  # Older captures retain arc length but no centerline sweep.
        return tuple(a + (b-a)*fraction for a,b in zip(start,end))
    dx, dy = mid[0]-start[0], mid[1]-start[1]
    ex, ey = end[0]-start[0], end[1]-start[1]
    cross = dx*ey-dy*ex
    if abs(cross) < 1e-14:
        return None
    m, n = dx*dx+dy*dy, ex*ex+ey*ey
    cx, cy = (m*ey-n*dy)/(2*cross), (dx*n-ex*m)/(2*cross)
    angle = math.atan2(-cy,-cx)
    sweep = (math.atan2(ey-cy,ex-cx)-angle) % math.tau
    if cross < 0:
        sweep -= math.tau
    radius = math.hypot(cx,cy)
    if not math.isclose(abs(sweep)*radius,track['length_mm'],rel_tol=1e-4,abs_tol=3e-6):
        return None
    angle += sweep*fraction
    return start[0]+cx+radius*math.cos(angle), start[1]+cy+radius*math.sin(angle)


def _choices(bundle, evidence):
    if bundle.get('request',{}).get('series'):
        from .series_power_tree import build_series_power_tree
        tree = build_series_power_tree(bundle, representative_lengths=True)
        return [(row['net'],row['wire_lengths']) for row in tree['nodes'] if row['kind']=='copper']
    request = bundle.get('request',{})
    net = request.get('net') or bundle.get('geometry',{}).get('net')
    units = bundle.get('terminal_units',{})
    if units:
        pads = evidence.get('pads',{})
        def pins(ids):
            return [dict(id=uid,label=pads.get(uid,{}).get('label',uid)) for uid in ids]
        sources = pins(units['source_terminals'])
        return [(net,copper_lengths(dict(net=net,incoming_pins=sources,
                     outgoing_pins=pins(load['terminals'])),evidence,representative=True)) for load in units['loads'][:24]]
    from .series_path_diagram import load_track_chains
    return [(net,rows) for rows in load_track_chains(request,evidence,representative=True)]


def resistance_profiles(bundle, evidence=None):
    """Provide JSON-safe known and unknown samples, one representative chain per load/stage."""
    import numpy as np

    result, mesh = bundle.get('result',{}), bundle.get('mesh',{})
    study = dict(status='UNAVAILABLE', notice=NOTICE, profiles=[], source_current_A=None)
    geometry = bundle.get('geometry') or mesh.get('geometry',{})
    evidence = bundle.get('path_geometry') or geometry.get('path_geometry') or evidence
    current = result.get('source_current_A')
    source = result.get('source_voltage_V')
    if not isinstance(current,(int,float)) or not math.isfinite(current) or current <= 0:
        study['reason'] = 'A positive solved source current is required.'
        return study
    study['source_current_A'] = current
    if mesh.get('tetrahedra') or not mesh.get('triangles') or not result.get('potential_V'):
        study['reason'] = 'A solved 2.5D copper potential field is required.'
        return study
    if not isinstance(source,(int,float)) or not math.isfinite(source) or not evidence:
        study['reason'] = 'The source voltage or saved track centerlines are unavailable.'
        return study
    xy = np.asarray(mesh['points_mm'],dtype=float)[:,:2]
    triangles = np.asarray(mesh['triangles'],dtype=int)
    values = np.asarray(result['potential_V'],dtype=float)
    layers = np.asarray([str(layer) for layer in mesh['triangle_layer']])
    nets = mesh_net_labels(bundle)
    if (triangles.ndim!=2 or triangles.shape[1]!=3 or len(layers)!=len(triangles)
            or len(nets)!=len(triangles) or len(values)!=len(xy)
            or triangles.min()<0 or triangles.max()>=len(xy) or not np.isfinite(xy).all()):
        raise ValueError('The saved mesh and nodal voltage inventories are inconsistent.')
    probes, tracks = {}, {row.get('id'):row for row in evidence.get('tracks',())}
    labels = {row['id']:row.get('label',row['id']) for row in geometry.get('terminals',())}
    choices = _choices(bundle,evidence)
    omitted = max(0,len(choices)-24)
    if bundle.get('terminal_units',{}).get('loads'):
        omitted = max(omitted,len(bundle['terminal_units']['loads'])-24)
    study['omitted_routes'] = omitted
    for net, group in choices[:24]:
        valid = [r for r in group if r.get('status')=='saved_track_chain' and r.get('track_ids')]
        if not valid:
            study['profiles'].append(dict(net=net, label=group[0].get('label',net) if group else net,
                length_mm=None, status='UNAVAILABLE', samples=[], reason='No continuous same-layer saved track chain.'))
            continue
        route = min(valid,key=lambda r:(r['length_mm'],r['from_pad'],r['to_pad']))
        start, target = route['from_pad'], route['to_pad']
        profile = dict(net=net,label=f'{labels.get(start,start)} → {labels.get(target,target)}',
                       from_pad=start,to_pad=target,length_mm=route['length_mm'],samples=[],status='UNAVAILABLE')
        study['profiles'].append(profile)
        ends, sections, point = [], [], tuple(evidence['pads'][start]['position_mm'])
        for uid in route['track_ids']:
            track = tracks.get(uid)
            if not track or track['net']!=net:
                break
            a,b=tuple(track['start_mm']),tuple(track['end_mm'])
            if point==b:
                a,b=b,a
            if a!=point:
                break
            sections.append((track,a,b))
            ends.append((ends[-1] if ends else 0.)+track['length_mm'])
            point=b
        if len(sections)!=len(route['track_ids']) or point!=tuple(evidence['pads'][target]['position_mm']):
            profile['reason']='Incomplete saved track identity or centerline endpoints.'
            continue
        distances=set(np.linspace(0.,ends[-1],97).tolist())
        if len(ends)<=256:
            distances.update(ends)
        for distance in sorted(distances):
            i=min(bisect_left(ends,distance),len(ends)-1)
            track,a,b=sections[i]
            fraction=(distance-(ends[i-1] if i else 0.))/track['length_mm']
            pos=_position(track,a,b,fraction)
            key=net,str(track['layer'])
            if key not in probes:
                probes[key]=SheetProbe(xy,triangles[(nets==net)&(layers==key[1])],values)
            voltage=probes[key].potential(*pos) if pos is not None else None
            profile['samples'].append(dict(distance_mm=distance,track_id=track['id'],layer=track['layer'],
                x_mm=pos[0] if pos else None,y_mm=pos[1] if pos else None,potential_V=voltage,
                resistance_ohm=(source-voltage)/current if voltage is not None else None))
        count=sum(row['resistance_ohm'] is not None for row in profile['samples'])
        profile['status']='SAMPLED' if count==len(profile['samples']) else 'PARTIAL' if count else 'UNAVAILABLE'
    states={p['status'] for p in study['profiles']}
    if states=={'SAMPLED'} and not omitted:
        study['status']='SAMPLED'
    elif states & {'SAMPLED','PARTIAL'}:
        study['status']='PARTIAL'
    else:
        study['reason']='No saved same-layer route has solved copper samples at the selected operating point.'
    return study


def draw_profile(axes, study, index=0):
    """Draw discrete solved samples; never draw a line across an unknown interval."""
    profile = study['profiles'][index] if study['profiles'] else {}
    rows=[row for row in profile.get('samples',[]) if row['resistance_ohm'] is not None]
    if rows:
        axes.scatter([row['distance_mm'] for row in rows], [1000*row['resistance_ohm'] for row in rows],
                     color='#087f82',s=13)
    else:
        axes.text(.5,.5,profile.get('reason') or study.get('reason','No solved copper samples.'),
                  transform=axes.transAxes,ha='center',va='center',wrap=True)
    if profile.get('length_mm'):
        axes.set_xlim(0,profile['length_mm'])
    axes.set_xlabel('Distance along saved track chain (mm)')
    axes.set_ylabel('Source-to-point voltage drop / total source current (mΩ)')
    axes.grid(alpha=.2)
    return axes
