"""Keep series electrode identity separate from the single-net picker state."""
from copy import deepcopy


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
