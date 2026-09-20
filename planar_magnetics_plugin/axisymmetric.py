"""Linear axisymmetric A-phi magnetostatic FEM on a bounded meridian domain.

First-order triangular Aphi basis. B=(-dAphi/dz, dAphi/dr + Aphi/r).
The weak form integrates 2*pi*r/mu * B(test).B(A), with azimuthal J source.
Axis and external edges impose Aphi=0. No nonlinear/hysteretic/eddy-current
material, arbitrary STEP meshing or Maxwell-stress force is claimed.
"""
from dataclasses import dataclass,asdict,replace
import math

MU0=4e-7*math.pi


@dataclass(frozen=True)
class AxisymmetricSpec:
    winding_inner_mm: float=8.
    winding_outer_mm: float=10.
    winding_height_mm: float=30.
    turns: int=100
    current_a: float=1.
    core_inner_mm: float=0.
    core_outer_mm: float=0.
    core_height_mm: float=30.
    core_mu_r: float=1.
    radial_cells: int=32
    axial_cells: int=64
    air_extent: float=3.


def validate(spec):
    if any(not math.isfinite(value) for value in asdict(spec).values()):raise ValueError('All field inputs must be finite')
    if not 0<spec.winding_inner_mm<spec.winding_outer_mm or spec.winding_height_mm<=0:raise ValueError('Winding radii must satisfy 0 < inner < outer; height must be positive')
    if spec.turns<=0 or int(spec.turns)!=spec.turns or spec.current_a==0:raise ValueError('Integer turns must be positive and current must be nonzero')
    if not 0<=spec.core_inner_mm<=spec.core_outer_mm<spec.winding_inner_mm or spec.core_height_mm<=0 or spec.core_mu_r<1:raise ValueError('Core must fit inside the winding bore, with positive height and relative permeability >= 1')
    if not 8<=spec.radial_cells<=160 or not 16<=spec.axial_cells<=320 or int(spec.radial_cells)!=spec.radial_cells or int(spec.axial_cells)!=spec.axial_cells:raise ValueError('Mesh requires 8–160 radial and 16–320 axial cells')
    if not 2<=spec.air_extent<=8:raise ValueError('Air extent must be between 2 and 8')


def solve(spec):
    validate(spec)
    try:
        import numpy as np
        from scipy.sparse import coo_matrix
        from scipy.sparse.linalg import spsolve
    except ImportError as exc:raise ValueError('Axisymmetric FEM requires NumPy and SciPy in the plugin runtime') from exc
    ri,ro,height=spec.winding_inner_mm*.001,spec.winding_outer_mm*.001,spec.winding_height_mm*.001
    ci,co,ch=spec.core_inner_mm*.001,spec.core_outer_mm*.001,spec.core_height_mm*.001
    radius=ro*spec.air_extent;half=max(height,ch)*.5*spec.air_extent
    # Feature-aligned grid avoids changing NI with centroid region rounding.
    radial=np.unique(np.r_[np.linspace(0,radius,int(spec.radial_cells)+1),ri,ro,ci,co])
    axial=np.unique(np.r_[np.linspace(-half,half,int(spec.axial_cells)+1),-height/2,height/2,-ch/2,ch/2,0.])
    nr,nz=len(radial),len(axial)
    if nr*nz>60000:raise ValueError('Field mesh exceeds 60,000 vertices')
    r,z=np.meshgrid(radial,axial);points=np.column_stack((r.ravel(),z.ravel()))
    ll=(np.arange(nz-1)[:,None]*nr+np.arange(nr-1)).ravel()
    triangles=np.vstack((np.column_stack((ll,ll+1,ll+nr+1)),np.column_stack((ll,ll+nr+1,ll+nr))))
    coords=points[triangles];centers=coords.mean(axis=1)
    det=(coords[:,1,0]-coords[:,0,0])*(coords[:,2,1]-coords[:,0,1])-(coords[:,2,0]-coords[:,0,0])*(coords[:,1,1]-coords[:,0,1])
    area=det*.5
    grad_r=np.column_stack((coords[:,1,1]-coords[:,2,1],coords[:,2,1]-coords[:,0,1],coords[:,0,1]-coords[:,1,1]))/det[:,None]
    grad_z=np.column_stack((coords[:,2,0]-coords[:,1,0],coords[:,0,0]-coords[:,2,0],coords[:,1,0]-coords[:,0,0]))/det[:,None]
    winding=(centers[:,0]>ri)&(centers[:,0]<ro)&(abs(centers[:,1])<height/2)
    core=(co>ci)&(centers[:,0]>ci)&(centers[:,0]<co)&(abs(centers[:,1])<ch/2)
    mu=np.where(core,MU0*spec.core_mu_r,MU0)
    density=np.where(winding,spec.turns*spec.current_a/((ro-ri)*height),0.)
    element=np.zeros((len(triangles),3,3));rhs_element=np.zeros((len(triangles),3))
    for basis in (np.array([2/3,1/6,1/6]),np.array([1/6,2/3,1/6]),np.array([1/6,1/6,2/3])):
        rq=coords[:,:,0]@basis;bz=grad_r+basis[None,:]/rq[:,None]
        weight=2*math.pi*rq*area/3
        element+=(weight/mu)[:,None,None]*(grad_z[:,:,None]*grad_z[:,None,:]+bz[:,:,None]*bz[:,None,:])
        rhs_element+=weight[:,None]*density[:,None]*basis[None,:]
    rows=np.repeat(triangles,3,axis=1).ravel();columns=np.tile(triangles,(1,3)).ravel()
    matrix=coo_matrix((element.ravel(),(rows,columns)),shape=(len(points),len(points))).tocsr()
    rhs=np.zeros(len(points));np.add.at(rhs,triangles.ravel(),rhs_element.ravel())
    boundary=(points[:,0]==0)|(points[:,0]==radius)|(abs(points[:,1])==half)
    free=np.flatnonzero(~boundary);a=np.zeros(len(points));a[free]=spsolve(matrix[free][:,free],rhs[free])
    residual=float(np.linalg.norm((matrix@a-rhs)[free])/max(np.linalg.norm(rhs[free]),1e-30))
    if not np.isfinite(a).all() or residual>1e-7:raise ValueError(f'Field solve failed residual check ({residual:g})')
    values=a[triangles];br=-np.sum(grad_z*values,axis=1);bz=np.sum(grad_r*values,axis=1)+values.mean(axis=1)/centers[:,0]
    energy=float(.5*a@(matrix@a));source_work=float(.5*a@rhs)
    if energy<=0 or abs(energy-source_work)>1e-7*energy:raise ValueError('Field energy/source-work consistency failed')
    mid=int(np.argmin(abs(axial)));axis_b=float(2*a[mid*nr+1]/radial[1])
    magnitude=np.hypot(br,bz)
    return dict(spec=asdict(spec),vertices_m=points.tolist(),triangles=triangles.tolist(),
        br_t=br.tolist(),bz_t=bz.tolist(),regions=np.where(winding,1,np.where(core,2,0)).tolist(),
        axis_center_b_t=axis_b,energy_j=energy,inductance_h=2*energy/spec.current_a**2,
        source_ampere_turns=float(np.sum(density*area)),relative_residual=residual,
        source_work_j=source_work,vertex_count=len(points),triangle_count=len(triangles),
        peak_b_t=float(magnitude.max()),core_peak_b_t=float(magnitude[core].max()) if np.any(core) else None,
        limitation='Linear axisymmetric magnetostatics; Aphi=0 finite external boundary; no eddy currents, hysteresis, nonlinear saturation or force integration.')


def analytic_air_axis_b(spec,z_m=0.):
    """Exact winding-thickness integral for a uniform finite air solenoid."""
    validate(spec)
    if spec.core_outer_mm>spec.core_inner_mm and spec.core_mu_r!=1:raise ValueError('Air reference is only valid without a magnetic core')
    ri,ro,height=spec.winding_inner_mm*.001,spec.winding_outer_mm*.001,spec.winding_height_mm*.001
    def radial_integral(offset):
        if offset==0:return 0.
        return offset*(math.asinh(ro/abs(offset))-math.asinh(ri/abs(offset)))
    return MU0*spec.turns*spec.current_a/(2*height*(ro-ri))*(radial_integral(z_m+height/2)-radial_integral(z_m-height/2))


def convergence(spec):
    """Three independent solves; preserve cell size when enlarging air domain."""
    validate(spec)
    if spec.radial_cells>64 or spec.axial_cells>128 or spec.air_extent>6:raise ValueError('Convergence review requires <=64×128 base cells and air extent <=6')
    base=solve(spec)
    refined=solve(replace(spec,radial_cells=spec.radial_cells*2,axial_cells=spec.axial_cells*2))
    enlarged=solve(replace(spec,radial_cells=round(spec.radial_cells*1.25),axial_cells=round(spec.axial_cells*1.25),air_extent=spec.air_extent*1.25))
    def change(first,second,key):return abs(first[key]-second[key])/max(abs(second[key]),1e-30)
    evidence=dict(mesh_l_change=change(base,refined,'inductance_h'),air_l_change=change(base,enlarged,'inductance_h'),
                  mesh_axis_b_change=change(base,refined,'axis_center_b_t'),air_axis_b_change=change(base,enlarged,'axis_center_b_t'))
    if spec.core_outer_mm==spec.core_inner_mm or spec.core_mu_r==1:
        reference=analytic_air_axis_b(spec);evidence['analytic_axis_b_t']=reference
        evidence['analytic_axis_b_relative_error']=abs(refined['axis_center_b_t']-reference)/abs(reference)
    return dict(base=base,evidence=evidence)


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Bounded linear axisymmetric magnetic FEM; geometry in mm, current in A.')
    parser.add_argument('--input',required=True,help='JSON object of AxisymmetricSpec fields')
    parser.add_argument('--output',required=True,help='Full result JSON including mesh and fields')
    parser.add_argument('--convergence',action='store_true',help='Also compare refined mesh and larger air domain')
    args=parser.parse_args(argv)
    try:
        source=Path(args.input).resolve();destination=Path(args.output).resolve()
        if source==destination:raise ValueError('Output must not overwrite the input specification')
        payload=json.loads(source.read_text(encoding='utf-8-sig'))
        if not isinstance(payload,dict):raise ValueError('Input specification must be a JSON object')
        spec=AxisymmetricSpec(**payload)
        result=convergence(spec) if args.convergence else dict(base=solve(spec),evidence={})
        destination.write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
        print(json.dumps(dict(output=str(destination),inductance_h=result['base']['inductance_h'],evidence=result['evidence'])))
    except (ValueError,TypeError,OSError) as exc:
        print(json.dumps(dict(error=str(exc))));return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
