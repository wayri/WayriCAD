"""Finite-width navigation through filled copper, including holes and spokes.

KiCad performs polygon offsets/fracturing. A boundary graph of the inward
offset polygon gives a connected route without a quadratic all-contact graph.
The returned polyline is shortened by visibility, then checked against actual
copper; it is a corridor approximation, not a sheet-current field solution.
"""
import heapq
import math

IU = 1_000_000


def xy(point):
    return int(point.x), int(point.y)


def length(a, b):
    return math.hypot(a[0]-b[0],a[1]-b[1])/IU


class ZoneNavigation:
    def __init__(self, geometry, island, width_mm):
        self.geometry, self.island, self.width_mm = geometry,island,width_mm
        pcb = geometry.pcb
        inset = pcb.SHAPE_POLY_SET(island.get('routing_poly',island['poly']))
        # The extra two microns cover polygon approximation error. This is
        # conservative: a corridor is never made wider than the actual copper.
        inset.Deflate(round(width_mm*IU/2)+2000,pcb.CORNER_STRATEGY_ROUND_ALL_CORNERS,1000)
        self.components = []
        for index in range(inset.OutlineCount()):
            poly=pcb.SHAPE_POLY_SET()
            poly.AddOutline(inset.COutline(index))
            for hole in range(inset.HoleCount(index)):
                poly.AddHole(inset.CHole(index,hole),0)
            self.components.append(poly)
        self._walks={}

    def component(self, p):
        vector=self.geometry.pcb.VECTOR2I(*p)
        return next((i for i,poly in enumerate(self.components) if poly.Contains(vector)),None)

    def _walk(self,index):
        if index not in self._walks:
            poly=self.geometry.pcb.SHAPE_POLY_SET(self.components[index])
            # Fracture joins holes to the outer contour by zero-area seams
            # through copper, yielding a walk usable without opaque SWIG triangles.
            poly.Fracture()
            chain=poly.COutline(0)
            self._walks[index]=[xy(chain.CPoint(i)) for i in range(chain.PointCount())]
        return self._walks[index]

    def route(self,a,b,index=None):
        fit=lambda p,q:self.geometry.fits(self.island,p,q,self.width_mm,routing=True)
        if fit(a,b):
            return [a,b]
        if index is None:
            index=self.component(a)
        if index is None or self.component(b)!=index:
            return None
        points=self._walk(index)
        if not points:
            return None
        def attach(p):
            # No vertex-count cutoff: examine nearest vertices until one is
            # visible. The fractured boundary graph connects every hole seam.
            return next((i for i in sorted(range(len(points)),key=lambda i:length(p,points[i]))
                         if fit(p,points[i])),None)
        ia,ib=attach(a),attach(b)
        if ia is None or ib is None:
            return None
        # Coincident seam vertices must share a node, or hole-to-outline bridge
        # walks can introduce needless entire-perimeter detours.
        graph={}
        for p,q in zip(points,points[1:]+points[:1]):
            graph.setdefault(p,[]).append(q)
            graph.setdefault(q,[]).append(p)
        source,target=points[ia],points[ib]
        queue=[(0.,source)]; costs={source:0.}; parent={}
        while queue:
            cost,p=heapq.heappop(queue)
            if cost!=costs[p]:continue
            if p==target:break
            for q in graph[p]:
                new=cost+length(p,q)
                if new<costs.get(q,math.inf):
                    costs[q]=new;parent[q]=p;heapq.heappush(queue,(new,q))
        if target not in costs:return None
        path=[target]
        while path[-1]!=source:path.append(parent[path[-1]])
        path=[a]+list(reversed(path))+[b]
        # Visibility string pulling retains bends needed to avoid actual voids.
        short=[path[0]];cursor=0
        while cursor<len(path)-1:
            stop=next((i for i in range(len(path)-1,cursor,-1) if fit(path[cursor],path[i])),None)
            if stop is None:return None
            short.append(path[stop]);cursor=stop
        return short
