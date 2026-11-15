"""Map exact saved UUIDs to PI inputs without guessing electrical direction."""


def selection_plan(identifiers, inventory, scene, role='net'):
    if role not in ('net', 'source', 'sink'):
        raise ValueError('Choose net, source or sink selection mode.')
    wanted = {str(value).casefold() for value in identifiers if value}
    if not wanted:
        raise ValueError('Select a connected track, pad or via in the originating PCB Editor.')
    primitives = scene.get('primitives', [])
    matched = [row for row in primitives if str(row.get('uuid', '')).casefold() in wanted
               or str(row.get('parent_uuid', '')).casefold() in wanted]
    terminals = [row for row in inventory.get('terminals', [])
                 if str(row.get('id', '')).casefold() in wanted]
    resolved = {str(row.get(key, '')).casefold() for row in matched
                for key in ('uuid', 'parent_uuid')}
    resolved.update(str(row['id']).casefold() for row in terminals)
    if wanted - resolved:
        raise ValueError('Some selected UUIDs are absent from this snapshot. Reload the saved board.')
    nets = {row.get('net') for row in matched + terminals if row.get('net')}
    if len(nets) != 1:
        raise ValueError('Select items on exactly one net; ambiguous selections leave inputs unchanged.')
    net = next(iter(nets))
    if net not in inventory.get('nets', []):
        raise ValueError('Selected net is absent from the saved snapshot. Reload the saved board.')
    terminal = None
    if role != 'net':
        choices = {row['id']: row for row in terminals if row.get('net') == net}
        if len(choices) != 1:
            raise ValueError('Select exactly one pad to assign this role; tracks and whole footprints have no direction.')
        terminal = next(iter(choices))
    return {'net': net, 'role': role, 'terminal': terminal}
