"""Original-sample relative radiation surfaces and principal-plane cuts."""
from dataclasses import dataclass
import math
import numbers

import numpy as np


CUTS = ('XZ cut', 'YZ cut', 'XY azimuth')


@dataclass(frozen=True)
class RadiationSamples:
    theta: np.ndarray
    phi: np.ndarray
    phi_original: np.ndarray
    magnitude: np.ndarray
    relative: np.ndarray
    frequency: float
    peak: float
    unknown: bool


def _axis(raw, name):
    if not isinstance(raw, (list, tuple, np.ndarray)):
        raise ValueError('Radiation '+name+' must be an angular sample axis.')
    if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real) for value in raw):
        raise ValueError('Radiation '+name+' contains invalid angles.')
    axis = np.array(raw, dtype=float, copy=True)
    if axis.ndim != 1 or len(axis)<2 or not np.isfinite(axis).all():
        raise ValueError('Radiation '+name+' requires at least two finite angles.')
    return axis


def prepare_radiation(raw, *, allow_zero=False):
    """Validate radians/[theta,phi] magnitudes; None stays unknown, not zero."""
    if not isinstance(raw, dict): raise ValueError('Radiation data were not recorded for this study.')
    try:
        theta,phi = _axis(raw['theta_rad'],'theta'),_axis(raw['phi_rad'],'phi')
        phi_original = phi.copy()
        if np.any(np.diff(theta)<=0) or theta[0]<0 or theta[-1]>math.pi+1e-12:
            raise ValueError('Radiation theta must increase between 0 and pi radians.')
        if not np.all(np.diff(phi)>0): phi = np.unwrap(phi)
        if np.any(np.diff(phi)<=0) or phi[-1]-phi[0]>2*math.pi+1e-12:
            raise ValueError('Radiation phi must increase through at most one full turn.')
        values = np.array(raw['norm_e'],dtype=object,copy=True)
        if values.shape != (len(theta),len(phi)):
            raise ValueError('Radiation magnitudes must have shape [theta, phi].')
        known = values != None
        if any(isinstance(value,(bool,np.bool_)) or not isinstance(value,numbers.Real) for value in values[known]):
            raise ValueError('Radiation magnitudes must be finite nonnegative numbers or unknown.')
        magnitude = np.array(values,dtype=float)
        if not np.isfinite(magnitude[known]).all() or np.any(magnitude[known]<0):
            raise ValueError('Radiation magnitudes contain negative or nonfinite values.')
        frequency = raw['frequency_hz']
        if isinstance(frequency,bool) or not isinstance(frequency,numbers.Real) or not math.isfinite(frequency) or frequency<=0:
            raise ValueError('Radiation frequency must be finite and positive.')
    except (KeyError,TypeError,OverflowError) as exc:
        raise ValueError('Invalid radiation sample structure.') from exc
    peak = float(np.max(magnitude[known])) if np.any(known) else 0.
    if peak<=0 and not allow_zero:
        raise ValueError('No positive known radiation samples; a normalized pattern is unavailable.')
    relative = magnitude/peak if peak>0 else np.where(known,0.,np.nan)
    for array in (theta,phi,phi_original,magnitude,relative): array.setflags(write=False)
    return RadiationSamples(theta,phi,phi_original,magnitude,relative,float(frequency),peak,bool(np.any(~known)))


def _nearest(axis, target, *, periodic=False):
    distance = np.abs(np.angle(np.exp(1j*(axis-target)))) if periodic else np.abs(axis-target)
    index = int(np.argmin(distance))
    if distance[index]<=1e-10: return index
    if periodic:
        physical=np.sort(np.mod(axis,2*math.pi))
        physical=physical[np.r_[True,np.diff(physical)>1e-10]]
        if len(physical)>1 and physical[0]+2*math.pi-physical[-1]<=1e-10: physical=physical[:-1]
        if len(physical)<2: return None
        spacing=np.diff(np.r_[physical,physical[0]+2*math.pi])
        nearest=np.unique(np.round(np.mod(axis[np.isclose(distance,distance[index],atol=1e-10,rtol=0)],2*math.pi),10))
        if len(nearest)>1: return None
    else:
        spacing=np.diff(axis)
        if np.sum(np.isclose(distance,distance[index],atol=1e-10,rtol=0))>1: return None
    tolerance = float(np.min(spacing[spacing>1e-12]))/2+1e-10
    return index if distance[index]<=tolerance else None


def sample_row(samples, i, j):
    """Retain the original angular indices and recorded value behind each probe."""
    relative = float(samples.relative[i,j])
    if not math.isfinite(relative): return None
    theta,phi = float(samples.theta[i]),float(samples.phi_original[j])
    return dict(kind='radiation',frequency_hz=samples.frequency,theta_deg=math.degrees(theta),
                phi_deg=math.degrees(phi),theta_index=int(i),phi_index=int(j),
                relative_e=relative,recorded_norm_e=float(samples.magnitude[i,j]),
                display_xyz=(relative*math.sin(theta)*math.cos(phi),relative*math.sin(theta)*math.sin(phi),relative*math.cos(theta)))


def radiation_cut(samples, name):
    """Select actual angular rows/columns; missing coverage remains an open gap."""
    if name not in CUTS: raise ValueError('Unknown radiation cut.')
    angles=[]; values=[]; rows=[]; descriptions=[]
    def add(i,j,angle):
        row=sample_row(samples,i,j)
        angles.append(float(angle));values.append(float(samples.relative[i,j]))
        rows.append(dict(row,angle_rad=float(angle)) if row else None)
    if name=='XY azimuth':
        i=_nearest(samples.theta,math.pi/2)
        if i is None: raise ValueError('No sampled theta near 90 degrees; the XY azimuth cut is unavailable.')
        for j,phi in enumerate(samples.phi): add(i,j,phi)
        descriptions.append(f'sampled θ={math.degrees(samples.theta[i]):.5g}°')
        convention='φ from +X toward +Y; θ=90° is the XY plane'
        if abs(samples.theta[i]-math.pi/2)>1e-10:
            convention=f'φ from +X toward +Y; sampled cone θ={math.degrees(samples.theta[i]):.5g}°, not the XY plane'
    else:
        positive,negative=(0.,math.pi) if name=='XZ cut' else (math.pi/2,-math.pi/2)
        first=_nearest(samples.phi,positive,periodic=True)
        rotated=False
        for branch,target in enumerate((positive,negative)):
            j=first if branch==0 else _nearest(samples.phi,target,periodic=True)
            if branch and first is not None:
                opposite=np.abs(np.angle(np.exp(1j*(samples.phi-samples.phi[first]-math.pi))))
                j=int(np.argmin(opposite)) if np.min(opposite)<=1e-10 else None
            if branch:
                angles.append(np.nan);values.append(np.nan);rows.append(None)
            if j is None:
                descriptions.append(f'φ={math.degrees(target):g}° half not sampled')
                continue
            descriptions.append(f'sampled φ={math.degrees(samples.phi_original[j]):.5g}°')
            rotated |= abs(np.angle(np.exp(1j*(samples.phi[j]-target))))>1e-10
            indices=range(len(samples.theta)) if branch==0 else range(len(samples.theta)-1,-1,-1)
            for i in indices: add(i,j,samples.theta[i] if branch==0 else 2*math.pi-samples.theta[i])
        convention='θ from +Z toward '+('+X' if name=='XZ cut' else '+Y')+' on the positive half'
        if rotated: convention='θ from +Z; each half follows its declared sampled φ, nearest the requested principal plane'
    if not any(row is not None for row in rows):
        raise ValueError('No known original samples for the selected radiation cut.')
    return dict(name=name,angles_rad=np.array(angles),relative_e=np.array(values),samples=rows,
                caption=' · '.join(descriptions),convention=convention,
                normalization='maximum known stored |E| across all angles',unknown=samples.unknown)


def available_cuts(samples):
    names=[]
    for name in CUTS:
        try: radiation_cut(samples,name)
        except ValueError: continue
        names.append(name)
    return names


def radiation_status(result):
    """Return view availability and an actionable reason without inventing data."""
    try:
        samples=prepare_radiation((result or {}).get('radiation'))
    except ValueError as exc:
        return None,str(exc)
    return samples,''


def resolve_probe(samples, probe):
    """Re-read a probe from original indices/angles; never trust its cached value."""
    if not isinstance(probe,dict): raise ValueError('Radiation probe must identify an original angular sample.')
    frequency=probe.get('frequency_hz')
    if isinstance(frequency,bool) or not isinstance(frequency,numbers.Real) or not math.isfinite(frequency) or not math.isclose(frequency,samples.frequency,rel_tol=1e-12):
        raise ValueError('Radiation probe frequency does not match the stored angular result.')
    if 'theta_index' in probe or 'phi_index' in probe:
        i,j=probe.get('theta_index'),probe.get('phi_index')
        if any(isinstance(value,(bool,np.bool_)) or not isinstance(value,numbers.Integral) for value in (i,j)):
            raise ValueError('Radiation probe indices must be original integer indices.')
        if not(0<=i<len(samples.theta) and 0<=j<len(samples.phi)):
            raise ValueError('Radiation probe index is outside the original sample grid.')
    else:
        for key in ('theta_deg','phi_deg'):
            value=probe.get(key)
            if isinstance(value,bool) or not isinstance(value,numbers.Real) or not math.isfinite(value):
                raise ValueError('Radiation probe needs original theta/phi angles or indices.')
        theta,phi=math.radians(probe['theta_deg']),math.radians(probe['phi_deg'])
        i=int(np.argmin(np.abs(samples.theta-theta)))
        j=int(np.argmin(np.abs(np.angle(np.exp(1j*(samples.phi_original-phi))))))
    actual_theta,actual_phi=float(samples.theta[i]),float(samples.phi_original[j])
    for key,actual,periodic in (('theta_deg',actual_theta,False),('phi_deg',actual_phi,True)):
        if key not in probe: continue
        value=probe[key]
        if isinstance(value,bool) or not isinstance(value,numbers.Real) or not math.isfinite(value):
            raise ValueError('Radiation probe contains an invalid stored angle.')
        delta=math.radians(value)-actual
        if periodic:delta=float(np.angle(np.exp(1j*delta)))
        if abs(delta)>1e-10:
            raise ValueError('Radiation probe angles do not match their original indices.')
    magnitude=float(samples.magnitude[i,j]);known=math.isfinite(magnitude)
    return dict(theta_index=int(i),phi_index=int(j),frequency_hz=samples.frequency,
                theta_deg=math.degrees(actual_theta),phi_deg=math.degrees(actual_phi),
                recorded_norm_e=magnitude if known else None,
                relative_e=float(samples.relative[i,j]) if known and samples.peak>0 else None,
                status='Original sample' if known and samples.peak>0 else 'Unknown / normalized pattern unavailable')
