"""Short presentation labels which never replace solver or saved PCB identities."""
from __future__ import annotations

import math


def _position(row):
    def finite(key):
        try:value=float(row.get(key))
        except (ValueError,TypeError):return math.inf
        return value if math.isfinite(value) else math.inf
    return finite('y_mm'),finite('x_mm'),str(row.get('id',''))


def _cell_label(identifier):
    try:
        index=int(identifier)
        if index>=0:return 'C'+str(index+1)
    except (ValueError,TypeError,OverflowError):pass
    return 'Copper cell'


class DisplayIDs:
    """Number physical vias in top-view reading order; number cells from one.

    All axial segments linked to one extracted via share its V number. Distinct
    saved objects at the same XY remain distinct. Without an extracted identity,
    an independent mesh barrel retains its own number rather than being guessed
    to share a physical via. Construction visits vias only, never all mesh cells.
    """
    def __init__(self,bundle):
        mesh=bundle.get('mesh',{})
        geometry=bundle.get('geometry') or mesh.get('geometry',{})
        physical={str(row['id']):row for row in geometry.get('vias',[]) if row.get('id') is not None}
        self.sources={};fallback={}
        # Match the longest declared native ID; never split arbitrary UUID text.
        for row in mesh.get('vias',[]):
            identifier=str(row['id'])
            parent=identifier
            while parent not in physical and ':' in parent:parent=parent.rpartition(':')[0]
            if parent not in physical:parent=None
            if parent is None:
                parent=identifier;fallback[parent]=row
            self.sources[identifier]=parent
        entries={**fallback,**physical}
        self.entries=entries
        self.vias={identifier:'V'+str(index+1) for index,(identifier,_) in enumerate(sorted(entries.items(),key=lambda item:_position(item[1])))}

    def label(self,kind,identifier):
        if kind=='sheet':return _cell_label(identifier)
        if kind=='via':return self.vias.get(self.sources.get(str(identifier),str(identifier)),'Via')
        return str(identifier)

    def record(self,row):
        return dict(row,display_id=self.label(row.get('kind'),row.get('id')))

    def metadata(self):
        return {'scheme':'wayricad.pi-display-ids/v1',
                'via_labels':{**self.vias,**{key:self.vias[parent] for key,parent in self.sources.items()}},
                'notice':'V numbers identify physical vias within this extracted model, ordered by Y then X; C numbers are one-based mesh cell indices. Raw solver and saved-object IDs remain unchanged.'}


def prepare_display_ids(bundle):
    """Attach small serializable label metadata once when a model is accepted."""
    bundle['display_identifiers']=DisplayIDs(bundle).metadata()
    return bundle['display_identifiers']


def display_label(bundle,kind,identifier):
    """Return a human label; source identities stay in the original record."""
    if kind=='sheet':return _cell_label(identifier)
    metadata=bundle.get('display_identifiers',{})
    if kind=='via' and metadata.get('scheme')=='wayricad.pi-display-ids/v1':
        label=metadata.get('via_labels',{}).get(str(identifier))
        if label:return label
    return DisplayIDs(bundle).label(kind,identifier)


def display_result(bundle):
    """Return a shallow presentation view; numerical arrays and raw IDs are kept."""
    result=bundle.get('result',{})
    if not result:return result
    prepared=bundle.get('display_identifiers',{}).get('scheme')=='wayricad.pi-display-ids/v1'
    labels=None if prepared else DisplayIDs(bundle)
    def record(row):
        return (dict(row,display_id=display_label(bundle,row.get('kind'),row.get('id')))
                if labels is None else labels.record(row))
    view=dict(result)
    if result.get('analytics'):
        analysis=dict(result['analytics'])
        for key in ('hotspots_by_current_density','hotspots_by_heating_density'):
            analysis[key]=[record(row) for row in analysis.get(key,[])]
        view['analytics']=analysis
    if result.get('fusing'):
        view['fusing']=dict(result['fusing'],bottlenecks=[record(row) for row in result['fusing'].get('bottlenecks',[])])
    return view
