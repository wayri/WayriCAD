"""Immutable cached triangle BVHs and packed rendering data for board inspection."""
from array import array
import math
import threading

from wayricad_runtime.picking import ray_box, triangle_hit


def pack_mesh(mesh):
    data = array('f')
    vertices = mesh['vertices']
    for face in mesh['faces']:
        a, b, c = (vertices[i] for i in face)
        u = [b[i]-a[i] for i in range(3)]
        v = [c[i]-a[i] for i in range(3)]
        normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        length = math.sqrt(sum(n*n for n in normal))
        if length < 1e-15:
            continue
        normal = [n/length for n in normal]
        for point in (a, b, c):
            data.extend((*point, *normal))
    return data


class TriangleIndex:
    def __init__(self, mesh, leaf_size=12):
        self.mesh = mesh
        self.tests = 0
        vertices = mesh['vertices']
        self.bounds = [tuple([min(vertices[i][axis] for i in face) for axis in range(3)]
                             + [max(vertices[i][axis] for i in face) for axis in range(3)])
                       for face in mesh['faces']]
        self.leaf_size = leaf_size
        self.root = self._build(list(range(len(self.bounds)))) if self.bounds else None

    def _build(self, indices):
        bounds = tuple([min(self.bounds[i][a] for i in indices) for a in range(3)]
                       + [max(self.bounds[i][a+3] for i in indices) for a in range(3)])
        if len(indices) <= self.leaf_size:
            return bounds, indices, None, None
        axis = max(range(3), key=lambda a: bounds[a+3]-bounds[a])
        indices.sort(key=lambda i: self.bounds[i][axis]+self.bounds[i][axis+3])
        mid = len(indices)//2
        return bounds, None, self._build(indices[:mid]), self._build(indices[mid:])

    def pick(self, origin, direction, accept=None, max_distance=math.inf):
        self.tests = 0
        result = None
        if self.root is None:
            return result
        stack = [self.root]
        while stack:
            bounds, indices, first, second = stack.pop()
            if not ray_box(origin, direction, bounds):
                continue
            if indices is None:
                stack.extend((first, second))
                continue
            for index in indices:
                if not ray_box(origin, direction, self.bounds[index]):
                    continue
                self.tests += 1
                value = triangle_hit(origin, direction,
                                     [self.mesh['vertices'][i] for i in self.mesh['faces'][index]])
                if value is None or value >= max_distance:
                    continue
                position = [a+value*d for a, d in zip(origin, direction)]
                if accept is not None and not accept(position):
                    continue
                max_distance = value
                result = {'position': position, 'distance': value}
        return result


class SceneIndex:
    """Prepare away from the GUI; publish each complete immutable body atomically."""
    def __init__(self, bodies):
        self.bodies = bodies
        self.prepared = {}
        self.cancel = threading.Event()
        self.ready = False
        self.tests = 0

    def prepare(self):
        for index, body in enumerate(self.bodies):
            if self.cancel.is_set():
                return
            mesh = body.get('mesh')
            if mesh and mesh.get('faces'):
                tree = TriangleIndex(mesh)
                packed = pack_mesh(mesh)
                if self.cancel.is_set():
                    return
                self.prepared[index] = tree, packed
        self.ready = True

    def pick(self, origin, direction, visible=lambda body: True, accept=None):
        best, distance = None, math.inf
        self.hit_body_index=None
        self.tests = 0
        for index, body in enumerate(self.bodies):
            prepared = self.prepared.get(index)
            if not prepared or not visible(body) or not ray_box(origin, direction, body['bounds']):
                continue
            tree = prepared[0]
            hit = tree.pick(origin, direction, accept, distance)
            self.tests += tree.tests
            if hit:
                best = dict(hit, reference=body['ref'])
                self.hit_body_index=index
                distance = hit['distance']
        return best
