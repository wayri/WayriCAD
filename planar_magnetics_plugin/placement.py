"""Conservative placement preflight for generated conductors.

Bounding boxes intentionally reserve uncertain pad/text/zone geometry. The tool
creates isolated winding/heater copper; users connect its terminals afterwards.
This prevents existing same-net copper from bypassing the intended conductor.
"""
from wayricad_runtime.geometry import segment_hits_box


def validate_placement(board, proposed, api):
    if not proposed:
        return
    rules=board.GetDesignSettings()
    minimum=getattr(rules,'m_MinClearance',None)
    if minimum is None:
        minimum=rules.GetSmallestClearanceValue()
    clearance=max(0,int(minimum))
    classes=getattr(board,'GetAllNetClasses',lambda:{})()
    clearance=max([clearance]+[int(c.GetClearance()) for c in classes.values()])
    boxes=[item.GetBoundingBox() for item in proposed]
    left=min(b.GetLeft() for b in boxes);right=max(b.GetRight() for b in boxes)
    top=min(b.GetTop() for b in boxes);bottom=max(b.GetBottom() for b in boxes)
    layers=list(board.GetEnabledLayers().CuStack())
    candidate_layers=[{layer for layer in layers if item.IsOnLayer(layer)} for item in proposed]
    used_layers=set().union(*candidate_layers)
    occupied=list(board.GetTracks())+list(board.GetDrawings())+list(board.Zones())
    for footprint in board.GetFootprints():
        occupied.extend(footprint.Pads())
        occupied.extend(footprint.GraphicalItems())
        occupied.extend(footprint.GetFields())
        # IPC returns zone items through the board query; native footprints
        # additionally expose their owned rule areas through Zones().
        occupied.extend(getattr(footprint,'Zones',lambda:[])())
    for item in occupied:
        shared=[layer for layer in used_layers if item.IsOnLayer(layer)]
        if not shared:
            continue
        box=item.GetBoundingBox()
        gap=clearance
        if hasattr(item,'GetLocalClearance'):
            gap=max(gap,int(item.GetLocalClearance() or 0))
        if hasattr(item,'GetOwnClearance'):
            gap=max([gap]+[int(item.GetOwnClearance(layer)) for layer in shared])
        if box.GetRight()+gap<left or box.GetLeft()-gap>right or box.GetBottom()+gap<top or box.GetTop()-gap>bottom:
            continue
        for candidate,active_layers in zip(proposed,candidate_layers):
            if not active_layers.intersection(shared):
                continue
            is_via=candidate.GetClass()=='PCB_VIA'
            width=candidate.GetWidth(candidate.TopLayer()) if is_via else candidate.GetWidth()
            start=candidate.GetPosition() if is_via else candidate.GetStart()
            end=start if is_via else candidate.GetEnd()
            if segment_hits_box(start,end,box,width/2+gap):
                owner=getattr(item,'GetParentFootprint',lambda:None)()
                ref=owner.GetReference() if owner else type(item).__name__
                names=', '.join(board.GetLayerName(layer) for layer in shared)
                raise ValueError(f'Generated copper overlaps reserved existing geometry near {ref} on {names}. '
                                 'Choose a clear placement area, review again, then connect the terminals afterwards. '
                                 'Pad, text and zone bounding boxes are reserved conservatively.')
