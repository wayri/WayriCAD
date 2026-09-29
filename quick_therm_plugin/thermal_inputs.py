"""Validate thermal form inputs without requiring a GUI runtime."""

import math


def _parse_sink_areas(text, references):
    """Map one or more virtual sinks to explicit exposed areas in mm²."""
    references = set(references)
    if not references:
        return {}
    text = str(text).strip()
    if len(references) == 1 and "=" not in text:
        area = float(text)
        if not math.isfinite(area) or area <= 0:
            raise ValueError("Sink exposed area must be positive.")
        return {next(iter(references)): area}
    areas = {}
    for item in text.replace(";", ",").split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError("Use REF=area pairs, e.g. U1=1200, U2=800.")
        ref, value = (part.strip() for part in item.split("=", 1))
        if ref in areas or ref not in references:
            raise ValueError("Unknown or duplicate heatsink reference: " + ref)
        area = float(value)
        if not math.isfinite(area) or area <= 0:
            raise ValueError(ref + ": exposed area must be positive.")
        areas[ref] = area
    if set(areas) != references:
        raise ValueError("Enter exposed area for each sink: " + ", ".join(sorted(references - set(areas))))
    return areas

