"""Deterministic net search; never turn a search string into a net assignment."""
def matching_nets(names, query):
    """Return original exact net names containing the case-insensitive query."""
    text = str(query).strip().casefold()
    return [name for name in names if text in str(name).casefold()]


def filter_combo(combo, names, query):
    """Filter a read-only wx combo while preserving its exact selected net."""
    chosen = combo.GetValue()
    visible = matching_nets(names, query)
    combo.Set(visible)
    if chosen in visible:
        combo.SetValue(chosen)
    else:
        combo.SetSelection(-1)
    return visible
