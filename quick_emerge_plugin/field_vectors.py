"""Phase-resolved vectors at original EM sample coordinates, never surrogate waves."""
import math
import numpy as np


def sample_vectors(field, quantity='E magnitude', phase_deg=0, z_index=None, limit=900):
    if quantity not in ('E magnitude', 'H magnitude'):
        raise ValueError('Phase vectors require saved complex E or H, not magnitude-only power/temperature.')
    if not math.isfinite(float(phase_deg)):
        raise ValueError('Phase must be finite.')
    prefix, unit = ('e', 'v_m') if quantity=='E magnitude' else ('h', 'a_m')
    raw = field.get('volume') if z_index is not None else field
    if raw is None or prefix+'_real_'+unit not in raw or prefix+'_imag_'+unit not in raw:
        raise ValueError('This result lacks complex vector components; rerun the solver to obtain them.')
    phasor = np.asarray(raw[prefix+'_real_'+unit], float) + 1j*np.asarray(raw[prefix+'_imag_'+unit], float)
    x, y = np.asarray(raw['x_mm']), np.asarray(raw['y_mm'])
    if any(a.ndim!=1 or len(a)<2 or not np.isfinite(a).all() or np.any(np.diff(a)<=0) for a in (x, y)):
        raise ValueError('Vector coordinates require finite, increasing original X/Y axes.')
    if isinstance(limit, bool) or not isinstance(limit, int) or limit<1:
        raise ValueError('Vector display limit must be a positive integer.')
    if z_index is not None:
        if isinstance(z_index, bool) or not isinstance(z_index, int) or not 0 <= z_index < len(raw['z_mm']):
            raise ValueError('Invalid original Z slice.')
        phasor = phasor[:, z_index]
        z = raw['z_mm'][z_index]
    else:
        z = raw['z_mm']
    if phasor.shape != (3, len(y), len(x)):
        raise ValueError('Complex vector shape must be components X/Y/Z first, then Y/X grid.')
    stride = max(1, int(math.ceil(math.sqrt(len(x)*len(y)/limit))))
    xx, yy = np.meshgrid(x[::stride], y[::stride])
    positions = np.column_stack((xx.ravel(), yy.ravel(), np.full(xx.size, z)))
    sampled = phasor[:, ::stride, ::stride].reshape(3, -1).T
    vectors = (sampled*np.exp(1j*np.deg2rad(phase_deg))).real
    valid = np.isfinite(vectors).all(axis=1) & np.isfinite(sampled).all(axis=1)
    positions, vectors, sampled = positions[valid], vectors[valid], sampled[valid]
    maximum = float(np.linalg.norm(sampled, axis=1).max()) if len(sampled) else 0
    pitch = min(np.min(np.abs(np.diff(a))) for a in (x, y) if len(a)>1)*stride
    return {'positions': positions, 'vectors': vectors, 'magnitudes': np.linalg.norm(vectors, axis=1),
            'arrow_scale_mm_per_unit': .7*pitch/maximum if maximum else 0,
            'phase_deg': float(phase_deg), 'stride': stride, 'unit': 'V/m' if prefix=='e' else 'A/m'}


def native(viewport, data):
    import vtk
    points, vectors = vtk.vtkPoints(), vtk.vtkDoubleArray()
    vectors.SetNumberOfComponents(3); vectors.SetName('Instantaneous field')
    for position, vector in zip(data['positions'], data['vectors']):
        points.InsertNextPoint(*position); vectors.InsertNextTuple(vector)
    poly = vtk.vtkPolyData(); poly.SetPoints(points); poly.GetPointData().SetVectors(vectors)
    source = vtk.vtkArrowSource()
    glyph = vtk.vtkGlyph3D(); glyph.SetInputData(poly); glyph.SetSourceConnection(source.GetOutputPort())
    glyph.SetVectorModeToUseVector(); glyph.SetScaleModeToScaleByVector()
    glyph.GeneratePointIdsOn(); glyph.SetPointIdsName('original_vector_index')
    glyph.SetScaleFactor(data['arrow_scale_mm_per_unit']); glyph.OrientOn(); glyph.Update()
    viewport.data_actor = viewport._actor(glyph.GetOutput(), (.05, .55, .7))


def plot(axes, data):
    if len(data['positions']):
        axes.quiver(*data['positions'].T, *(data['vectors']*data['arrow_scale_mm_per_unit']).T,
                    color='#098caa', normalize=False, arrow_length_ratio=.25)
