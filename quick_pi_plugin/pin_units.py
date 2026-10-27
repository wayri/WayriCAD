"""Recommend same-footprint/net pads without changing the load's total current."""
from __future__ import annotations

import re

from .terminals import pad_names


def anchor(spec):
    """Return the UI anchor for a singular or grouped endpoint specification."""
    return spec.get('terminal') or spec.get('id') or pad_names(spec)[0]


def peers(terminals, identifier, excluded=()):
    """Return same-net pads owned by the exact footprint UUID, in pin order.

    A reference string alone cannot distinguish unannotated/duplicate parts.
    Old inventories lacking footprint identity deliberately give no suggestion.
    """
    matches=[row for row in terminals if row['id']==identifier]
    if len(matches)!=1:return []
    chosen=matches[0];owner=chosen.get('footprint_uuid');net=chosen.get('net')
    if not owner or not net:return []
    blocked=set(excluded)|{identifier}
    def order(row):
        return tuple((0,int(value)) if value.isdigit() else (1,value.casefold())
                     for value in re.split(r'(\d+)',str(row.get('pad_number',row.get('label',row['id'])))))
    return sorted((row for row in terminals if row['id'] not in blocked
                   and row.get('footprint_uuid')==owner and row.get('net')==net),key=order)


def unit(spec, extra_ids=()):
    """Make one ideal equipotential unit; current_A remains a total, not per pin."""
    identifier=anchor(spec);ids=list(dict.fromkeys([identifier,*extra_ids]))
    result={key:value for key,value in spec.items() if key not in ('terminal','terminals')}
    if len(ids)>1:
        result.update(id=identifier,terminals=ids)
    else:
        result['terminal']=identifier
    return result


def validate_units(source_ids, sinks):
    """Prevent one physical pad from belonging to multiple endpoint units."""
    occupied=set(source_ids)
    if len(occupied)!=len(source_ids):raise ValueError('Repeated source pad.')
    for spec in sinks:
        ids=pad_names(spec)
        if occupied.intersection(ids):
            raise ValueError('A pad cannot be shared between source and sink units or multiple sinks.')
        occupied.update(ids)
