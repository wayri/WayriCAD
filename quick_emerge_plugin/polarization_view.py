"""Boresight polarization geometry derived only from saved complex components."""
import numpy as np


def ellipse(result):
    pol = result.get('radiation', {}).get('boresight_polarization')
    if not pol:
        raise ValueError('No saved complex boresight Ex/Ey; polarization is unavailable.')
    ex, ey = complex(*pol['ex_ri']), complex(*pol['ey_ri'])
    scale = np.sqrt(abs(ex)**2 + abs(ey)**2)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Boresight polarization is zero or non-finite.')
    phase = np.linspace(0, 2*np.pi, 181)
    return np.column_stack(((ex*np.exp(1j*phase)).real/scale,
                            (ey*np.exp(1j*phase)).real/scale, np.zeros(len(phase))))


def available(result):
    try:
        ellipse(result or {})
        return True
    except (ValueError, KeyError, TypeError):
        return False


def plot(figure, result, options=None):
    points = ellipse(result)
    figure.clear()
    axes = figure.add_subplot(111, projection='3d')
    axes.plot(*points.T, color='#13899a', linewidth=2)
    axes.quiver(0, 0, 0, 0, 0, 1, color='#d27d2c')
    axes.set(xlabel='Ex / sqrt(S0)', ylabel='Ey / sqrt(S0)', zlabel='+Z direction',
             xlim=(-1, 1), ylim=(-1, 1), zlim=(-1, 1),
             title='Saved +Z boresight polarization ellipse; normalized field\nNot a board-space field or angular polarization map')
    axes.set_box_aspect((1, 1, 1))


def native(viewport, result):
    import vtk
    points = ellipse(result)
    vertices = vtk.vtkPoints()
    for point in points:
        vertices.InsertNextPoint(*point)
    line = vtk.vtkPolyLine()
    line.GetPointIds().SetNumberOfIds(len(points))
    for i in range(len(points)):
        line.GetPointIds().SetId(i, i)
    cells = vtk.vtkCellArray()
    cells.InsertNextCell(line)
    data = vtk.vtkPolyData()
    data.SetPoints(vertices)
    data.SetLines(cells)
    actor = viewport._actor(data, (.07, .6, .65))
    actor.GetProperty().SetLineWidth(3)
    viewport._line((0, 0, 0), (0, 0, 1), (.85, .4, .1))
