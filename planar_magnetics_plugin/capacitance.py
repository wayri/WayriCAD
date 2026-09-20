"""Explicit-dielectric capacitance models; electrostatic C is not magnetic L.

Interwinding: two equipotential annular conductors, homogeneous dielectric,
axisymmetric scalar-potential FEM. Outer enclosure is an explicit reference.
"""
import math
EPS0=8.8541878128e-12


def _positive(value,name):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<=0:raise ValueError(name+' must be positive and finite')
    return float(value)


def _winding(data):
    if not isinstance(data,dict):raise ValueError('Winding must be a geometry object')
    ri,ro,h=(_positive(data.get(k),k)*.001 for k in ('winding_inner_mm','winding_outer_mm','winding_height_mm'))
    z=data.get('z_offset_mm',0.)
    if isinstance(z,bool) or not isinstance(z,(int,float)) or not math.isfinite(z):raise ValueError('Winding offset must be finite')
    if ri>=ro:raise ValueError('Winding inner radius must be smaller than outer radius')
    return ri,ro,h,z*.001


def solve_interwinding(primary,secondary,*,epsilon_r,domain_radius_mm,domain_half_height_mm,
                       radial_cells=40,axial_cells=80,axial_boundary='grounded'):
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve
    er=_positive(epsilon_r,'Explicit uniform relative permittivity')
    radius=_positive(domain_radius_mm,'Domain radius')*.001;half=_positive(domain_half_height_mm,'Domain half height')*.001
    coils=[_winding(primary),_winding(secondary)]
    if axial_boundary not in ('grounded','insulated'):raise ValueError('Axial boundary must be grounded or insulated')
    for ri,ro,h,z in coils:
        if ro>=radius or abs(z)+h/2>half or (axial_boundary=='grounded' and abs(z)+h/2>=half):raise ValueError('Conductors must fit strictly inside grounded enclosure')
    a,b=coils
    if min(a[1],b[1])>=max(a[0],b[0]) and min(a[3]+a[2]/2,b[3]+b[2]/2)>=max(a[3]-a[2]/2,b[3]-b[2]/2):raise ValueError('Conductors overlap or touch')
    if any(isinstance(n,bool) or not isinstance(n,int) for n in (radial_cells,axial_cells)) or not 8<=radial_cells<=160 or not 16<=axial_cells<=320:raise ValueError('Mesh requires 8–160 radial / 16–320 axial cells')
    def aligned(base,features):
        features=np.unique(features);features=features[np.r_[True,np.diff(features)>1e-13]]
        keep=np.ones(len(base),dtype=bool)
        for f in features:keep &= abs(base-f)>1e-13
        return np.unique(np.r_[base[keep],features])
    rr=aligned(np.linspace(0,radius,radial_cells+1),[0,radius,*[v for ri,ro,h,z in coils for v in (ri,ro)]])
    zz=aligned(np.linspace(-half,half,axial_cells+1),[-half,half,*[v for ri,ro,h,z in coils for v in (z-h/2,z+h/2)]])
    nr,nz=len(rr),len(zz)
    if nr*nz>60000:raise ValueError('Electrostatic mesh exceeds 60,000 vertices')
    r,z=np.meshgrid(rr,zz);points=np.column_stack((r.ravel(),z.ravel()))
    ll=(np.arange(nz-1)[:,None]*nr+np.arange(nr-1)).ravel()
    tri=np.vstack((np.column_stack((ll,ll+1,ll+nr+1)),np.column_stack((ll,ll+nr+1,ll+nr))))
    xy=points[tri];mid=xy.mean(axis=1)
    def inside(p,c,tol=0):
        ri,ro,h,z=c
        return (p[:,0]>=ri-tol)&(p[:,0]<=ro+tol)&(p[:,1]>=z-h/2-tol)&(p[:,1]<=z+h/2+tol)
    dielectric=~(inside(mid,a)|inside(mid,b));tri=tri[dielectric];xy=points[tri];mid=xy.mean(axis=1)
    det=(xy[:,1,0]-xy[:,0,0])*(xy[:,2,1]-xy[:,0,1])-(xy[:,2,0]-xy[:,0,0])*(xy[:,1,1]-xy[:,0,1])
    gr=np.column_stack((xy[:,1,1]-xy[:,2,1],xy[:,2,1]-xy[:,0,1],xy[:,0,1]-xy[:,1,1]))/det[:,None]
    gz=np.column_stack((xy[:,2,0]-xy[:,1,0],xy[:,0,0]-xy[:,2,0],xy[:,1,0]-xy[:,0,0]))/det[:,None]
    elements=(2*math.pi*EPS0*er*mid[:,0]*det/2)[:,None,None]*(gr[:,:,None]*gr[:,None,:]+gz[:,:,None]*gz[:,None,:])
    matrix=coo_matrix((elements.ravel(),(np.repeat(tri,3,axis=1).ravel(),np.tile(tri,(1,3)).ravel())),shape=(len(points),len(points))).tocsr()
    electrodes=[inside(points,c,1e-13) for c in coils]
    ground=points[:,0]==radius
    if axial_boundary=='grounded':ground |= abs(points[:,1])==half
    fixed=ground|electrodes[0]|electrodes[1];free=np.flatnonzero(~fixed)
    potential=np.zeros((len(points),2))
    for index,mask in enumerate(electrodes):potential[mask,index]=1.
    rhs=-(matrix@potential)[free]
    potential[free]=spsolve(matrix[free][:,free],rhs)
    charges=matrix@potential
    capacitance=np.array([[charges[mask].sum(axis=0) for mask in electrodes]])[0]
    energy=potential.T@charges
    residual=np.linalg.norm(charges[free],axis=0)/np.maximum(np.linalg.norm(rhs,axis=0),1e-30)
    reciprocal=float(np.linalg.norm(capacitance-capacitance.T)/max(np.linalg.norm(capacitance),1e-30))
    error=float(np.linalg.norm(energy-capacitance)/max(np.linalg.norm(capacitance),1e-30))
    if not np.isfinite(potential).all() or residual.max()>1e-7 or reciprocal>1e-7 or error>1e-7:raise ValueError('Electrostatic residual/energy/reciprocity check failed')
    capacitance=(capacitance+capacitance.T)/2
    eigenvalues=np.linalg.eigvalsh(capacitance)
    environment=capacitance.sum(axis=1);mutual=-float(capacitance[0,1])
    if eigenvalues.min()<=0 or mutual<=0 or np.any(environment < -1e-8*capacitance.max()):raise ValueError('Nonphysical Maxwell capacitance matrix')
    return dict(schema='wayricad.axisymmetric-capacitance/v1',C_matrix_F=capacitance.tolist(),interwinding_F=mutual,
                primary_environment_F=max(0.,float(environment[0])),secondary_environment_F=max(0.,float(environment[1])),
                evidence=dict(relative_residuals=residual.tolist(),reciprocity_relative_error=reciprocal,energy_relative_error=error,
                    epsilon_r=er,domain_radius_mm=domain_radius_mm,domain_half_height_mm=domain_half_height_mm,axial_boundary=axial_boundary,
                    primary=dict(primary),secondary=dict(secondary),vertex_count=len(points),triangle_count=len(tri),eigenvalues_F=eigenvalues.tolist(),
                    assumptions=['Uniform explicitly supplied dielectric everywhere outside the conductors; no inferred core/insulation permittivity.',
                    'Each complete winding is equipotential. Mutual branch C=-C12; environment branches are Maxwell row sums to the specified enclosure.',
                    'This common-mode surrogate is not a turn-distributed terminal capacitance. Do not automatically add it to an intrawinding estimate.',
                    'Finite grounded enclosure, linear dielectric, no conductive/magnetic core model. Mesh and enclosure sensitivity require review.']),
                field=dict(vertices_m=points.tolist(),triangles=tri.tolist(),potential_V=potential[:,0].tolist(),excitation='Primary 1 V; secondary and enclosure 0 V'))


def adjacent_round_wire(*,turns,wire_diameter_mm,pitch_mm,mean_turn_length_mm,epsilon_r):
    """Isolated adjacent round-wire pairs in a uniform dielectric; long wires."""
    if isinstance(turns,bool) or not isinstance(turns,int) or turns<2:raise ValueError('At least two integer turns required')
    d=_positive(wire_diameter_mm,'Wire diameter');pitch=_positive(pitch_mm,'Wire pitch')
    length=_positive(mean_turn_length_mm,'Mean turn length')*.001;er=_positive(epsilon_r,'Relative permittivity')
    if pitch<=d:raise ValueError('Insulated wire pitch must exceed conductor diameter')
    pair=math.pi*EPS0*er*length/math.acosh(pitch/d)
    return dict(terminal_capacitance_F=(turns-1)*pair/(turns*turns),adjacent_pair_F=pair,
        assumptions=['Round wires only, uniform dielectric, straight locally parallel segments; curvature/end/nonadjacent shielding ignored.',
                     'Linear voltage along N turns: adjacent turn-center difference is terminal voltage/N; terminal C from stored energy.',
                     'Not a PCB rectangular-trace or multilayer winding extraction; do not combine blindly with equipotential interwinding FEM.'])


def estimate_pcb_sidewall(result,*,epsilon_r,winding='Primary'):
    """Adjacent straight-segment sidewall energy, explicitly excluding fringing.

    Only a single continuous generated layer is supported. This partial
    contribution is not a complete terminal C or a self-resonance prediction.
    """
    er=_positive(epsilon_r,'Explicit sidewall dielectric permittivity')
    segments=[s for s in result.segments if s.winding==winding]
    if not segments or len({s.layer for s in segments})!=1:raise ValueError('Sidewall model requires one generated winding layer; interlayer/via potential distribution is unsupported')
    if len(segments)>2000:raise ValueError('Sidewall pair review is limited to 2000 segments')
    if result.spec.shape!='Rectangular spiral':raise ValueError('Sidewall model supports generated rectangular spirals; curved/fringing fields need electrostatic extraction')
    thickness=_positive(result.spec.copper_um,'Copper thickness')*1e-6
    gap_target=_positive(result.spec.spacing_mm,'Adjacent trace spacing')
    total=sum(s.length_mm for s in segments);offset=[];length=0.
    for index,s in enumerate(segments):
        if s.length_mm<=0:raise ValueError('Zero-length generated segment')
        if index and math.hypot(s.x1_mm-segments[index-1].x2_mm,s.y1_mm-segments[index-1].y2_mm)>1e-7:raise ValueError('Generated path is discontinuous; potential ordering is undefined')
        offset.append(length);length+=s.length_mm
    pairs=[]
    for i,a in enumerate(segments):
        ux=(a.x2_mm-a.x1_mm)/a.length_mm;uy=(a.y2_mm-a.y1_mm)/a.length_mm
        for j in range(i+2,len(segments)):
            b=segments[j];vx=(b.x2_mm-b.x1_mm)/b.length_mm;vy=(b.y2_mm-b.y1_mm)/b.length_mm
            if abs(ux*vy-uy*vx)>1e-10:continue
            dx=b.x1_mm-a.x1_mm;dy=b.y1_mm-a.y1_mm
            gap=abs(dx*uy-dy*ux)-(a.width_mm+b.width_mm)/2
            if gap<=0 or abs(gap-gap_target)>max(1e-7,gap_target*.001):continue
            start=dx*ux+dy*uy;direction=ux*vx+uy*vy
            lo=max(0.,min(start,start+direction*b.length_mm));hi=min(a.length_mm,max(start,start+direction*b.length_mm))
            if hi-lo<=1e-9:continue
            def delta(x):return (offset[i]+x-offset[j]-(x-start)/direction)/total
            d0,d1=delta(lo),delta(hi)
            pair=EPS0*er*thickness*((hi-lo)*.001)/(gap*.001)
            effective=pair*(d0*d0+d0*d1+d1*d1)/3
            pairs.append(dict(segment_indices=[i,j],overlap_mm=hi-lo,gap_mm=gap,pair_F=pair,terminal_energy_contribution_F=effective))
    if not pairs:raise ValueError('No adjacent parallel sidewalls found in generated geometry')
    return dict(schema='wayricad.pcb-sidewall-capacitance/v1',terminal_capacitance_F=sum(p['terminal_energy_contribution_F'] for p in pairs),
                pairs=pairs,epsilon_r=er,source='actual generated single-layer rectangular winding segments',
                coverage='PARTIAL_SIDEWALL_ONLY',assumptions=['Linear voltage versus conductor arc length; integrated Cij times squared normalized local voltage difference.',
                'Only adjacent parallel copper sidewalls at the generated trace spacing. Uniform explicitly supplied gap dielectric.',
                'Fringing, broad-face coupling, substrate interfaces, nonadjacent conductors and surroundings are excluded. Not full terminal capacitance or SRF validation.',
                'Do not add blindly to equipotential whole-winding interwinding extraction; those use a different potential distribution.'])
