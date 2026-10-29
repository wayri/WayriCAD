"""Typed sampled-network extensions and isolated public EMerge fitting.

Components are ideal linear R/L/C elements with explicit SI units. A shunt
branch joins one terminal to reference, or two specified network terminal
nodes. A series element joins one external terminal to the corresponding
original network terminal. No physical component/package parasitics, EM fields,
ports, geometry or lumped feeds are inferred or recomputed.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.metadata
import json
import math
from pathlib import Path

import numpy as np

from .network import SampledNetwork, _numeric


UNITS={'R':'ohm','L':'H','C':'F'}


def serialize_network(network):
    if not isinstance(network,SampledNetwork):raise ValueError('Expected a validated SampledNetwork')
    return {'schema':1,'kind':'sampled-network','frequencies_hz':network.frequencies_hz.tolist(),
            'port_count':network.port_count,'port_names':list(network.port_names),
            'reference_impedance_ohm':network.z0_ohm.tolist(),'wave_convention':'real-reference-power',
            's_parameters':{f'S{i+1}{j+1}':np.stack((network.s[:,i,j].real,network.s[:,i,j].imag),axis=-1).tolist() for i in range(network.port_count) for j in range(network.port_count)},
            'network_sha256':network.digest(),'provenance':deepcopy(network.provenance)}


def deserialize_network(payload):
    from .network import from_result
    if not isinstance(payload,dict) or type(payload.get('schema')) is not int or payload['schema']!=1 or payload.get('kind')!='sampled-network' or payload.get('wave_convention')!='real-reference-power':raise ValueError('Unsupported sampled-network serialization')
    network=from_result({**payload,'config':{'z0_ohm':50}})
    if payload.get('network_sha256')!=network.digest():raise ValueError('Derived-network numerical hash does not match its samples/references/port order')
    return SampledNetwork(network.frequencies_hz,network.s,network.z0_ohm,network.port_names,payload.get('provenance'))


def validate_components(network,components):
    if not isinstance(components,list) or not 1<=len(components)<=64:raise ValueError('Provide 1 to 64 typed component descriptions')
    normalized=[]
    for item in components:
        if not isinstance(item,dict) or set(item)!={'connection','element','value_si','unit','ports'}:raise ValueError('Component needs connection, element, value_si, unit and ports')
        element=item['element'];connection=item['connection']
        if not isinstance(element,str) or element not in UNITS or item['unit']!=UNITS[element] or connection not in ('shunt','series'):raise ValueError('Component kind, connection or SI unit is unsupported')
        value=_numeric(item['value_si'],float,'component value')
        if value.ndim or value<=0:raise ValueError('Component value must be a finite positive SI scalar')
        ports=item['ports']
        if not isinstance(ports,list) or len(ports) not in ((1,2) if connection=='shunt' else (1,)):raise ValueError('Shunt needs one or two nodes; series needs exactly one terminal')
        indices=[network._index(p) for p in ports]
        if len(set(indices))!=len(indices):raise ValueError('Component terminals must be distinct')
        normalized.append({'connection':connection,'element':element,'value_si':float(value),'unit':UNITS[element],
                           'ports':[network.port_names[i] for i in indices]})
    return normalized


def embed_components(network,components):
    """Exact sampled Y/Z stamping; representation singularities are errors.

    Each component is applied in listed order. Shunts use Y'=Y+y vv^T,
    v=e_p or e_p-e_n. Series insertion at terminal p uses Z'=Z+z e_p e_p^T.
    Mixed series/shunt ordering can change the circuit topology and is retained.
    """
    items=validate_components(network,components)
    out=network
    omega=2*np.pi*network.frequencies_hz
    for item in items:
        p=[out._index(name) for name in item['ports']]
        value=item['value_si'];element=item['element']
        impedance=np.full(len(omega),value,complex) if element=='R' else 1j*omega*value if element=='L' else 1/(1j*omega*value)
        stamp=np.zeros((out.port_count,out.port_count),complex)
        stamp[p[0],p[0]]=1
        if len(p)==2:
            stamp[p[1],p[1]]=1;stamp[p[0],p[1]]=stamp[p[1],p[0]]=-1
        history=deepcopy(out.provenance)
        history.setdefault('origin_network_sha256',network.digest())
        history.setdefault('transformations',[]).append({'operation':'embed_component',**item})
        if item['connection']=='shunt':
            matrix=out.to_y()+stamp[None,:,:]/impedance[:,None,None]
            out=SampledNetwork.from_y(out.frequencies_hz,matrix,out.z0_ohm,out.port_names,history)
        else:
            matrix=out.to_z()+stamp[None,:,:]*impedance[:,None,None]
            out=SampledNetwork.from_z(out.frequencies_hz,matrix,out.z0_ohm,out.port_names,history)
    return out


def _upstream_grid(network):
    """Use public dataset creation and fit methods; never import private fit code."""
    try:
        import emerge as em
    except ImportError as exc:raise RuntimeError('Rational fitting requires the selected EMerge 3 solver runtime') from exc
    version=importlib.metadata.version('emerge')
    if not version.startswith('3.'):raise RuntimeError('This rational-fit adapter requires EMerge 3 public scalar dataset APIs')
    model=em.Simulation('SampledNetworkFit')
    scalar=model.data.mw.scalar
    ports=list(range(1,network.port_count+1))
    for k,f in enumerate(network.frequencies_hz):
        entry=scalar.new(freq=float(f));entry.freq=float(f)
        entry.init_sp(ports)
        entry.k0=float(2*np.pi*f/em.lib.C0)
        entry.Z0[:]=network.z0_ohm
        for i in ports:
            for j in ports:entry.write_S(i,j,network.s[k,i-1,j-1])
    return scalar.grid,version


def _fit_values(network,frequencies,method,tolerance,poles):
    grid,version=_upstream_grid(network)
    values=np.asarray(grid.model_Smat(np.asarray(frequencies),method=method,tol=tolerance,Npoles=poles),dtype=complex)
    if values.shape!=(len(frequencies),network.port_count,network.port_count) or not np.isfinite(values).all():raise ValueError('Upstream fit produced nonfinite or malformed values; no fitted network was published')
    return values,version


def rational_fit(network,evaluation_frequencies_hz,*,method='aaa',tolerance=5e-4,poles=6):
    """Evaluate an actual upstream rational fit strictly inside the source band.

    Training residual is checked against all original samples. A separate model
    trained without alternating interior samples predicts those held-out data;
    this diagnostic is never called a guarantee of unsampled-band accuracy.
    Returned interpolated samples remain explicitly separate from EM samples.
    """
    if len(network.frequencies_hz)<5:raise ValueError('Rational fitting requires at least five original samples')
    if len(network.frequencies_hz)>200 or network.port_count>9:raise ValueError('Fitting is bounded to 200 source samples and 9 ports')
    f=_numeric(evaluation_frequencies_hz,float,'fit evaluation frequencies')
    if f.ndim!=1 or not 2<=len(f)<=2001 or np.any(np.diff(f)<=0) or f[0]<network.frequencies_hz[0] or f[-1]>network.frequencies_hz[-1]:raise ValueError('Fit evaluation needs 2 to 2001 strictly ordered frequencies inside the original band')
    tol=_numeric(tolerance,float,'fit tolerance')
    if tol.ndim or not 0<float(tol)<1:raise ValueError('Fit tolerance must be between zero and one')
    if method not in ('aaa','vf'):raise ValueError('Fit method must be aaa or vf')
    if isinstance(poles,bool) or not isinstance(poles,int) or not 1<=poles<=(min(30,len(network.frequencies_hz)-2) if method=='vf' else 30):raise ValueError('VF poles must be 1 to min(30, source samples - 2)')
    combined=np.unique(np.concatenate((network.frequencies_hz,f)))
    values,version=_fit_values(network,combined,method,float(tol),poles)
    on_source=values[np.searchsorted(combined,network.frequencies_hz)]
    on_evaluation=values[np.searchsorted(combined,f)]
    error=np.abs(on_source-network.s)
    held_indices=np.arange(1,len(network.frequencies_hz)-1,2)
    training=np.array([i for i in range(len(network.frequencies_hz)) if i not in held_indices])
    subset=SampledNetwork(network.frequencies_hz[training],network.s[training],network.z0_ohm,network.port_names,network.provenance)
    holdout=None;holdout_error=None
    try:
        predictions,_=_fit_values(subset,network.frequencies_hz[held_indices],method,float(tol),min(poles,max(1,len(training)-2)))
        holdout_error=np.abs(predictions-network.s[held_indices])
    except (ValueError,RuntimeError,np.linalg.LinAlgError) as exc:
        holdout=str(exc)
    history=deepcopy(network.provenance)
    history.setdefault('origin_network_sha256',network.digest())
    history.setdefault('transformations',[]).append({'operation':'rational_fit','method':method,'backend':'EMerge','version':version,'tolerance':float(tol),'poles':poles if method=='vf' else None,'source_frequency_count':len(network.frequencies_hz),'evaluation_frequency_count':len(f)})
    fitted=SampledNetwork(f,on_evaluation,network.z0_ohm,network.port_names,history)
    info={'method':method,'backend':'EMerge','version':version,'public_api':'Simulation.data.mw.scalar.grid.model_Smat',
          'absolute_tolerance_requested':float(tol),'poles_requested':poles if method=='vf' else None,
          'source_sample_count':len(network.frequencies_hz),'sample_max_abs_error':float(np.max(error)),
          'sample_rms_abs_error':float(np.sqrt(np.mean(error**2))),
          'sample_max_abs_error_by_entry':np.max(error,axis=0).tolist(),
          'tolerance_met':bool(np.max(error)<=float(tol)),
          'holdout_frequency_hz':network.frequencies_hz[held_indices].tolist(),
          'holdout_training_frequency_hz':network.frequencies_hz[training].tolist(),
          'holdout_max_abs_error':float(np.max(holdout_error)) if holdout_error is not None else None,
          'holdout_rms_abs_error':float(np.sqrt(np.mean(holdout_error**2))) if holdout_error is not None else None,
          'holdout_unavailable_reason':holdout,
          'limits':['Fitted values are approximations, not newly solved electromagnetic samples.',
                    'Training residual and held-out sampled errors do not establish mesh convergence, causality, stability or broadband accuracy.',
                    'No passivity enforcement is applied. No extrapolation outside the source frequency band is supported.']}
    return {'derived_network':serialize_network(fitted),'fit':info,'original_network_sha256':network.digest()}


def diagnostics(network):
    a=network.analyze()
    return {k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in a.items() if k in ('largest_singular_value','passivity_excess','sampled_passive','reciprocity_error','sampled_reciprocal','tolerance','limits')}


def touchstone_text(network,*,reference_ohm=None):
    """Touchstone 1.x RI with legacy 2-port order and row-major N>=3.

    Format reference: IBIS Touchstone 2.1, network-data ordering (v1 compatible).
    Unequal references require an explicit common-reference renormalization.
    No precision truncation or dB display floor alters exported complex samples.
    """
    if reference_ohm is not None:
        z=_numeric(reference_ohm,float,'export reference')
        if z.ndim or z<=0:raise ValueError('Touchstone export reference must be positive real scalar ohms')
        network=network.renormalize(float(z))
    if np.any(network.z0_ohm!=network.z0_ohm[0]):raise ValueError('Touchstone 1.x export needs a common real reference; explicitly choose reference_ohm')
    labels=[name.replace('\r',' ').replace('\n',' ') for name in network.port_names]
    lines=['! Quick EMerge derived sampled network; retain companion JSON provenance',
           '! SHA256 numerical network '+network.digest(), '! Ports '+json.dumps(labels,ensure_ascii=True),
           '# Hz S RI R '+format(float(network.z0_ohm[0]),'.17g')]
    n=network.port_count
    order=[(0,0),(1,0),(0,1),(1,1)] if n==2 else [(i,j) for i in range(n) for j in range(n)]
    for k,f in enumerate(network.frequencies_hz):
        pairs=[(format(network.s[k,i,j].real,'.17g'),format(network.s[k,i,j].imag,'.17g')) for i,j in order]
        if n<=2:lines.append(format(f,'.17g')+' '+' '.join(v for pair in pairs for v in pair))
        else:
            for row in range(n):
                lines.append((format(f,'.17g') if row==0 else ' ')+' '+' '.join(v for pair in pairs[row*n:(row+1)*n] for v in pair))
    return '\n'.join(lines)+'\n'


def export_touchstone(path,network,*,reference_ohm=None,source_paths=()):
    """Recoverably publish Touchstone and complete network evidence together."""
    from wayricad_runtime.report_ui import publish_documents
    path=Path(path)
    if path.suffix.lower()!=f'.s{network.port_count}p':raise ValueError('Touchstone destination extension must match the port count')
    exported=network if reference_ohm is None else network.renormalize(reference_ohm)
    content=touchstone_text(network,reference_ohm=reference_ohm)
    evidence=path.with_suffix(path.suffix+'.json')
    publish_documents({path:content,evidence:json.dumps(serialize_network(exported),indent=2,allow_nan=False)+'\n'},sources=source_paths)
    return {'touchstone':str(path),'json':str(evidence)}


def apply_operation(network,operation):
    """Closed typed operation dispatcher; no expression or arbitrary code input."""
    if not isinstance(operation,dict) or not isinstance(operation.get('kind'),str):raise ValueError('Network operation must be a typed object')
    kind=operation['kind']
    keys={'renormalize':{'kind','reference_ohm'},'mixed_mode':{'kind','pairs'},'terminate':{'kind','keep','loads_ohm'},
          'components':{'kind','components'},'fit':{'kind','method','tolerance','points','poles'}}
    if kind not in keys or set(operation)-keys[kind]:raise ValueError('Unknown network operation or arguments')
    if kind=='fit':
        points=operation.get('points',201)
        if type(points) is not int or not 2<=points<=2001:raise ValueError('Fit points must be 2 to 2001')
        return rational_fit(network,np.linspace(network.frequencies_hz[0],network.frequencies_hz[-1],points),method=operation.get('method','aaa'),tolerance=operation.get('tolerance',5e-4),poles=operation.get('poles',min(6,len(network.frequencies_hz)-2)))
    if kind=='renormalize':out=network.renormalize(operation['reference_ohm'])
    elif kind=='mixed_mode':out=network.mixed_mode(operation['pairs'])
    elif kind=='terminate':
        loads=operation['loads_ohm']
        # JSON keys are port names. Numeric GUI indices should be passed as names.
        out=network.terminate(operation['keep'],loads)
    else:out=embed_components(network,operation['components'])
    return {'derived_network':serialize_network(out),'original_network_sha256':network.digest()}
