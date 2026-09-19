"""Small 2-D quasi-static rectangular-grid electrostatic solver, stdlib with optional NumPy acceleration.

Solves div(epsilon grad V)=0 using a weighted finite-volume stencil and
preconditioned conjugate gradients. Uniform-line Z and delay are inferred from
C and a second vacuum solve C0. This is NOT full-wave SI/PI, loss extraction,
manufacturing qualification or a solver for arbitrary three-dimensional vias.
"""
import math
from dataclasses import dataclass, asdict

EPS0=8.8541878128e-12
C0=299792458.0


class Cancelled(RuntimeError):pass


@dataclass
class FieldResult:
    impedance_ohm: float
    capacitance_pf_per_m: float
    vacuum_capacitance_pf_per_m: float
    effective_permittivity: float
    delay_ps_per_mm: float
    iterations: int
    relative_residual: float
    grid: tuple
    warning: str
    potential: list = None


def electrostatic(nx,ny,width_m,height_m,epsilon,fixed,tolerance=1e-8,max_iterations=3000,cancel=None):
    """epsilon is a positive nx*ny nodal relative-permittivity list.
    fixed maps indices to potentials in volts. Every outer boundary must be fixed.
    Returns total energy*2 per length (F*V²/m), potential, iterations, residual.
    """
    if not (5<=nx<=241 and 5<=ny<=241):raise ValueError('Grid dimensions must be 5..241')
    n=nx*ny
    if len(epsilon)!=n or any(not math.isfinite(x) or x<=0 for x in epsilon):raise ValueError('Invalid dielectric grid')
    if not all(math.isfinite(x) and x>0 for x in (width_m,height_m,tolerance)):raise ValueError('Positive finite dimensions/tolerance required')
    if max_iterations<1:raise ValueError('Positive iteration limit required')
    if any(not isinstance(i,int) or not 0<=i<n or not math.isfinite(v) for i,v in fixed.items()):raise ValueError('Invalid conductor potential')
    boundary={y*nx+x for y in range(ny) for x in range(nx) if x in (0,nx-1) or y in (0,ny-1)}
    if not boundary<=fixed.keys():raise ValueError('The finite solve box needs explicit boundary conditions')
    dx,dy=width_m/(nx-1),height_m/(ny-1)
    free=[i for i in range(n) if i not in fixed];index={i:k for k,i in enumerate(free)}
    neighbors=[];diag=[];rhs=[]
    def weight(i,j):
        er=2*epsilon[i]*epsilon[j]/(epsilon[i]+epsilon[j])
        horizontal=abs(j-i)==1
        half=.5 if (horizontal and i//nx in (0,ny-1)) or (not horizontal and i%nx in (0,nx-1)) else 1.
        return half*er*(dy/dx if horizontal else dx/dy)
    for i in free:
        row=[];d=b=0.
        for j in (i-1,i+1,i-nx,i+nx):
            g=weight(i,j);d+=g
            if j in fixed:b+=g*fixed[j]
            else:row.append((index[j],g))
        neighbors.append(row);diag.append(d);rhs.append(b)
    def apply(v):return [d*x-sum(g*v[j] for j,g in row) for d,x,row in zip(diag,v,neighbors)]
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    # Optional NumPy acceleration. The same stencil/CG tolerance is used; no
    # dependency is downloaded and the pure-stdlib path remains usable.
    try:import numpy as np
    except ImportError:np=None
    if np is not None and free:
        d=np.asarray(diag);right=np.asarray(rhs);lookup=np.full((len(free),4),len(free),dtype=np.int64);weights=np.zeros((len(free),4))
        for k,row in enumerate(neighbors):
            for j,(idx,g) in enumerate(row):lookup[k,j]=idx;weights[k,j]=g
        def fast_apply(v):
            padded=np.append(v,0.)
            return d*v-np.sum(weights*padded[lookup],axis=1)
        x=np.zeros(len(free));r=right.copy();z=r/d;p=z.copy();rz=float(np.sum(r*z))
        norm=float(np.sqrt(np.sum(right*right)));relative=0. if norm==0 else 1.;iterations=0
        if norm:
            for iterations in range(1,max_iterations+1):
                if cancel and cancel():raise Cancelled('Field solve cancelled')
                ap=fast_apply(p);denom=float(np.sum(p*ap))
                if denom<=0:raise ArithmeticError('Non-positive solver matrix or numerical breakdown')
                alpha=rz/denom;x+=alpha*p;r-=alpha*ap;relative=float(np.sqrt(np.sum(r*r)))/norm
                if relative<tolerance:break
                z=r/d;new=float(np.sum(r*z));p=z+(new/rz)*p;rz=new
            else:raise ArithmeticError(f'Field solver did not converge: residual {relative:.3g}')
        x=x.tolist()
    else:
        x=[0.]*len(free);r=rhs[:];z=[r0/d for r0,d in zip(r,diag)];p=z[:];rz=dot(r,z)
        norm=math.sqrt(dot(rhs,rhs));relative=0. if norm==0 else 1.;iterations=0
        if norm:
            for iterations in range(1,max_iterations+1):
                if cancel and cancel():raise Cancelled('Field solve cancelled')
                ap=apply(p);denom=dot(p,ap)
                if denom<=0:raise ArithmeticError('Non-positive solver matrix or numerical breakdown')
                alpha=rz/denom
                x=[v+alpha*d for v,d in zip(x,p)];r=[v-alpha*d for v,d in zip(r,ap)]
                relative=math.sqrt(dot(r,r))/norm
                if relative<tolerance:break
                z=[v/d for v,d in zip(r,diag)];new=dot(r,z);beta=new/rz
                p=[v+beta*d for v,d in zip(z,p)];rz=new
            else:raise ArithmeticError(f'Field solver did not converge: residual {relative:.3g}')
    potential=[fixed.get(i,0.) for i in range(n)]
    for i,v in zip(free,x):potential[i]=v
    energy2=0.
    for y in range(ny):
        for xx in range(nx):
            i=y*nx+xx
            for j in ([i+1] if xx<nx-1 else [])+([i+nx] if y<ny-1 else []):
                energy2+=weight(i,j)*(potential[i]-potential[j])**2
    return EPS0*energy2,potential,iterations,relative


def uniform_line(width_mm,height_mm,er,gap_mm=None,kind='microstrip',nx=101,ny=61,cancel=None,domain_scale=1.):
    """Zero-thickness single trace or symmetric odd-mode pair over ideal grounds.
    Trace widths/gaps/heights are snapped to grid; actual dimensions are returned
    through the GUI's solver report. Refine the grid and box before relying on it.
    """
    w,h,er=float(width_mm),float(height_mm),float(er)
    if any(not math.isfinite(v) or v<=0 for v in (w,h,er)) or er<1:raise ValueError('Width/height must be positive; dielectric epsilon_r must be at least 1')
    if kind not in ('microstrip','stripline'):raise ValueError('Choose microstrip or symmetric stripline')
    if gap_mm is not None:
        gap_mm=float(gap_mm)
        if not math.isfinite(gap_mm) or gap_mm<=0:raise ValueError('Differential gap must be positive')
    nx=int(nx)|1;ny=int(ny)|1
    if not math.isfinite(domain_scale) or domain_scale<1:raise ValueError('Domain scale must be at least 1')
    span=(w if gap_mm is None else 2*w+gap_mm)+12*h*domain_scale
    boxheight=6*h*domain_scale if kind=='microstrip' else 2*h
    dx,dy=span/(nx-1),boxheight/(ny-1)
    if w/dx<2:raise ValueError('Trace narrower than two grid intervals: increase resolution or reduce the air box')
    if gap_mm is not None and gap_mm/dx<2:raise ValueError('Pair gap narrower than two grid intervals')
    jtrace=round(h/dy)
    fixed={j*nx+i:0. for j in range(ny) for i in range(nx) if i in (0,nx-1) or j in (0,ny-1)}
    actual=[]
    ranges=[(-w/2,w/2,1.)] if gap_mm is None else [(-gap_mm/2-w,-gap_mm/2,.5),(gap_mm/2,gap_mm/2+w,-.5)]
    for low,high,v in ranges:
        il=round((span/2+low)/dx);ir=round((span/2+high)/dx)
        actual.append({'left_mm':il*dx-span/2,'right_mm':ir*dx-span/2,'width_mm':(ir-il)*dx,'height_mm':jtrace*dy})
        for i in range(il,ir+1):fixed[jtrace*nx+i]=v
    epsilon=[er if kind=='stripline' or j<jtrace else (er+1)/2 if j==jtrace else 1. for j in range(ny) for i in range(nx)]
    cap,v,it,res=electrostatic(nx,ny,span/1000,boxheight/1000,epsilon,fixed,cancel=cancel)
    vacuum,_,it0,res0=electrostatic(nx,ny,span/1000,boxheight/1000,[1.]*(nx*ny),fixed,cancel=cancel)
    if cap<=0 or vacuum<=0:raise ArithmeticError('Non-positive capacitance')
    effective=cap/vacuum;z=1/(C0*math.sqrt(cap*vacuum))
    warn=f'2-D quasi-static, zero-thickness ideal conductor; finite grounded box {span:g} × {boxheight:g} mm. Grid {dx:g} × {dy:g} mm; snapped conductor dimensions: {actual}. No loss, dispersion, soldermask, roughness, vias or discontinuities. Requires mesh AND domain convergence; not manufacturing sign-off.'
    return FieldResult(z,cap*1e12,vacuum*1e12,effective,1e9*math.sqrt(effective)/C0,it+it0,max(res,res0),(nx,ny),warn,v)


def convergence(width_mm,height_mm,er,gap_mm=None,kind='microstrip',cancel=None):
    try:import numpy;fast=True
    except ImportError:fast=False
    grids=((81,49),(161,97),(241,145 if kind=='microstrip' else 97)) if fast else ((41,25),(81,49),(121,73 if kind=='microstrip' else 49))
    coarse=uniform_line(width_mm,height_mm,er,gap_mm,kind,*grids[0],cancel)
    fine=uniform_line(width_mm,height_mm,er,gap_mm,kind,*grids[1],cancel)
    change=abs(fine.impedance_ohm-coarse.impedance_ohm)/fine.impedance_ohm*100
    expanded=uniform_line(width_mm,height_mm,er,gap_mm,kind,*grids[2],cancel,domain_scale=1.5)
    domainchange=abs(expanded.impedance_ohm-fine.impedance_ohm)/expanded.impedance_ohm*100
    return {'numpy_accelerated':fast,'coarse':asdict(coarse)|{'potential':None},'fine':asdict(fine)|{'potential':None},
            'expanded_domain':asdict(expanded)|{'potential':None},
            'impedance_change_percent':change,'mesh_converged_2_percent':change<2,
            'domain_change_percent':domainchange,'domain_convergence_tested':True,
            'domain_converged_2_percent':domainchange<2,'converged_2_percent':change<2 and domainchange<2,
            'qualification':'Heuristic convergence indicators only. Grid snapping changes represented dimensions; independently compare physical geometry and external references.', 'signoff':False}
