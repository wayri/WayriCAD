"""Keep a load's physical pad identities stable while editing other load units."""
from .terminals import pad_names


def reserved_pads(source, primary, additional, *, editing=None):
    reserved = set(source) | set(primary)
    for index, row in enumerate(additional):
        if index != editing:
            reserved.update(pad_names(row))
    return reserved


def ordered_pads(wanted, anchor, terminals, blocked):
    """Keep the display anchor first when selected. Reject invalid or reused pads."""
    ids = list(wanted)
    pad_names({'terminals':ids})
    known = {row['id'] for row in terminals}
    if not set(ids).issubset(known):
        raise ValueError('Some chosen pads are missing from this net. Refresh the PCB and review them.')
    if set(ids) & set(blocked):
        raise ValueError('A pad is already assigned to the source or another sink.')
    if anchor in ids:
        ids.remove(anchor)
        ids.insert(0, anchor)
    return ids


def group_caption(ids, labels):
    names = [labels.get(key, key) for key in ids]
    if len(names) <= 4:
        return ', '.join(names)
    return ', '.join(names[:3]) + f' … ({len(names)} pads)'


def choose_pads(parent, terminals, chosen, blocked, anchor):
    """Use the common searchable, multi-select physical-pad picker on the active net."""
    from .pi_return_setup import choose_pad_unit
    options = [row for row in terminals if row['id'] not in blocked]
    if not options:
        raise ValueError('Every pad on this net is assigned to another unit.')
    net = options[0]['net']
    wanted = choose_pad_unit(parent, {'terminals':options}, net, chosen)
    return None if wanted is None else ordered_pads(wanted, anchor, options, blocked)
