"""Keep series electrode identity separate from the single-net picker state."""
from copy import deepcopy


def rebind_series(request, previous, current):
    """Keep every reviewed electrode bound to the same pad, footprint and net."""
    from .series_editor import draft_from_request
    updated=deepcopy(request)
    before=previous.get('terminals',[])
    by_id={}
    for row in current.get('terminals',[]):
        by_id.setdefault(row['id'],[]).append(row)

    def bind(value):
        old=[row for row in before if value in (row['id'],row.get('label'))]
        if len(old)==1:
            old=old[0]
            matches=by_id.get(old['id'],[])
            if len(matches)==1 and all(matches[0].get(key)==old.get(key)
                                       for key in ('net','footprint_uuid')):
                return old['id']
        raise ValueError('A series pad is missing, ambiguous or moved to a different net or footprint.')

    for row,roles in [(updated,(('source_terminal','source_terminals'),('sink_terminal','sink_terminals'))),
                      *((branch,(('from_pad','from_pads'),('to_pad','to_pads')))
                        for stage in updated['series'] for branch in (stage,*stage.get('parallel',[])))]:
        for anchor,group in roles:
            row[anchor]=bind(row[anchor])
            if group in row:
                row[group]=[bind(value) for value in row[group]]
    for key in ('source_sha256','expected_source_sha256'):
        if key in updated:
            updated[key]=current.get('source_sha256')
    draft_from_request(updated,current)
    return updated


def restore_endpoints(frame, request):
    rows=frame.inventory.get('terminals',[])
    chosen=[]
    for key in ('source_terminal','sink_terminal'):
        matches=[row for row in rows if request.get(key) in (row['id'],row.get('label'))]
        if len(matches)!=1:
            raise ValueError('Saved series endpoint is missing or ambiguous: '+key)
        chosen.append(matches[0])
    if chosen[0]['id']==chosen[1]['id']:
        raise ValueError('Series source and sink must be distinct pads.')
    frame._terminals=chosen
    from .console import terminal_aliases
    aliases=terminal_aliases(frame.inventory)
    labels=[aliases[row['id']] for row in chosen]
    frame.source.Set(labels);frame.sink.Set(labels)
    frame.source.SetSelection(0);frame.sink.SetSelection(1)


def display_request(request, inventory):
    """Readable console copy; UUIDs remain authoritative in the real request."""
    from .console import terminal_aliases
    labels=terminal_aliases(inventory)
    for row in inventory.get('terminals',[]):
        if row.get('footprint_uuid') and row.get('reference'):
            labels[row['footprint_uuid']]=row['reference']
    def visit(value):
        if isinstance(value,str):return labels.get(value,value)
        if isinstance(value,list):return [visit(item) for item in value]
        if isinstance(value,dict):return {key:visit(item) for key,item in value.items()}
        return deepcopy(value)
    return visit(request)
