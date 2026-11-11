"""Evidence-bound comparisons between solver output and published targets."""
from __future__ import annotations

import math


def _db(pair):
    magnitude = abs(complex(*pair))
    return 20.0 * math.log10(magnitude) if magnitude else -math.inf


def _band_check(result, port, band_ghz, label):
    low, high = (value * 1e9 for value in band_ghz)
    samples = [(frequency, _db(pair)) for frequency, pair in zip(
        result["frequencies_hz"], result["s_parameters"][f"S{port}{port}"])
        if low <= frequency <= high]
    if not samples:
        return {"check": label, "status": "insufficient", "detail": "No solved sample lies inside the published band."}
    best_frequency, best_db = min(samples, key=lambda item: item[1])
    return {"check": label, "status": "pass" if best_db <= -10.0 else "fail",
            "best_frequency_hz": best_frequency, "best_s_db": best_db,
            "criterion": "at least one sampled |Sii| <= -10 dB inside the published band"}


def _active_reflection_pairs(result, weights):
    power = sum(abs(value) ** 2 for value in weights)
    pairs = []
    for index, frequency in enumerate(result["frequencies_hz"]):
        outgoing = []
        for response in range(1, len(weights) + 1):
            outgoing.append(sum(complex(*result["s_parameters"][f"S{response}{excitation}"][index]) *
                                weights[excitation - 1] for excitation in range(1, len(weights) + 1)))
        gamma = math.sqrt(sum(abs(value) ** 2 for value in outgoing) / power)
        pairs.append((frequency, 20.0 * math.log10(gamma) if gamma else -math.inf))
    return pairs


def _sampled_band_check(samples, band_ghz, label, criterion):
    low, high = (value * 1e9 for value in band_ghz)
    inside = [sample for sample in samples if low <= sample[0] <= high]
    if not inside:
        return {"check": label, "status": "insufficient", "detail": "No solved sample lies inside the published band."}
    best_frequency, best_db = min(inside, key=lambda item: item[1])
    return {"check": label, "status": "pass" if best_db <= -10.0 else "fail",
            "best_frequency_hz": best_frequency, "best_s_db": best_db, "criterion": criterion}


def _axial_ratio_band_check(polarization, band_ghz, label):
    if not polarization or polarization.get("axial_ratio_db") is None:
        return {"check": label, "status": "insufficient",
                "detail": "Result has no finite boresight complex-field axial ratio."}
    frequency = polarization.get("frequency_hz")
    if frequency is None:
        return {"check": label, "status": "insufficient",
                "detail": "Boresight axial-ratio sample has no recorded frequency."}
    low, high = (value * 1e9 for value in band_ghz)
    if not low <= frequency <= high:
        return {"check": label, "status": "insufficient", "frequency_hz": frequency,
                "published_band_ghz": band_ghz,
                "detail": "The solved radiation frequency lies outside the published axial-ratio band."}
    value = polarization["axial_ratio_db"]
    return {"check": label, "status": "pass" if value < 3.0 else "fail",
            "frequency_hz": frequency, "axial_ratio_db": value,
            "criterion": "boresight AR < 3 dB at a solved frequency inside the published AR band"}


def compare_with_publication(result):
    """Compare only observables that exist in both result and source evidence."""
    research = result.get("research")
    if not research:
        raise ValueError("result does not contain research benchmark metadata")
    template_id = research["id"]
    checks = []
    if template_id == "verho-2023-aesa-4x4":
        limit = research["published_targets"]["maximum_steering_error_deg"]
        error = abs(result["array_factor"]["scan_error_deg"])
        checks.append({"check": "ideal scan-law peak", "status": "pass" if error <= limit else "fail",
                       "error_deg": error, "criterion_deg": limit,
                       "detail": "This checks the ideal scan law, not measured active-network error."})
    elif template_id == "yang-2016-wlan-monopole":
        for index, band in enumerate(research["published_targets"]["simulated_bands_ghz"], 1):
            checks.append(_band_check(result, 1, band, f"published WLAN band {index}"))
    elif template_id == "liu-2020-cubesat-yagi":
        checks.append(_band_check(result, 1, research["published_targets"]["deployed_90deg_band_ghz"],
                                  "published 90-degree deployed S-band"))
    elif template_id == "kabir-2023-cubesat-sx-shared-aperture":
        excitation = result["config"]["advanced"]["research_excitation"]
        if excitation == "auto":
            excitation = "s-band" if sum(result["frequencies_hz"]) / len(result["frequencies_hz"]) < 5e9 else "x-band"
        port, prefix = (1, "s_band") if excitation == "s-band" else (2, "x_band")
        checks.append(_band_check(result, port, research["published_targets"][prefix + "_s11_ghz"],
                                  f"published {excitation} return-loss band"))
        polarization = result.get("radiation", {}).get("boresight_polarization")
        if polarization:
            polarization = {**polarization, "frequency_hz": result["radiation"].get("frequency_hz")}
        checks.append(_axial_ratio_band_check(
            polarization, research["published_targets"][prefix + "_ar_ghz"],
            f"{excitation} boresight axial ratio"))
    elif template_id == "rezaeipour-2021-dual-feed-patch":
        target = research["published_targets"]["circular_resonance_ghz"]
        excitation = result["config"]["advanced"]["research_excitation"]
        weights = {"auto": [2 ** -0.5, 2 ** -0.5],
                   "linear": [2 ** -0.5, 2 ** -0.5],
                   "rhcp": [2 ** -0.5, -1j * 2 ** -0.5],
                   "lhcp": [2 ** -0.5, 1j * 2 ** -0.5]}[excitation]
        reflection = _sampled_band_check(
            _active_reflection_pairs(result, weights), [target * 0.955, target * 1.045],
            "coherent two-probe reflected-power context",
            "total reflected/incident coherent power ratio <= -10 dB")
        reflection["status"] = "insufficient"
        reflection["detail"] = (
            "The paper reports common-input matching through an omitted feed network; "
            "the model's two-probe coherent reflected-power ratio is not directly comparable to that S11."
        )
        checks.append(reflection)
        polarization = result.get("radiation", {}).get("boresight_polarization")
        if excitation in ("rhcp", "lhcp"):
            if polarization:
                polarization = {**polarization, "frequency_hz": result.get("radiation", {}).get("frequency_hz")}
            band_key = "measured_rhcp_ar_band_ghz" if excitation == "rhcp" else "measured_lhcp_ar_band_ghz"
            checks.append(_axial_ratio_band_check(
                polarization, research["published_targets"][band_key],
                "boresight circular-polarization axial ratio"))
        else:
            checks.append({"check": "boresight circular-polarization axial ratio", "status": "insufficient",
                           "detail": "The selected equal-phase state is linear; circular-polarization AR is not applicable."})
    elif template_id == 'cheh-lin-2023-siw-dra':
        for index, band in enumerate(research['published_targets']['measured_bands_ghz'], 1):
            checks.append(_band_check(result, 1, band, f'published SIW/DRA matching band {index}'))
        checks.append({'check': 'source geometry assumptions and convergence', 'status': 'insufficient',
                       'detail': research['model_scope']})
    elif template_id == 'ma-2024-siw-horn':
        checks.append(_band_check(result, 1, research['published_targets']['simulated_band_ghz'],
                                  'published SIW horn simulated matching band'))
        checks.append({'check': 'source geometry assumptions and convergence', 'status': 'insufficient',
                       'detail': research['model_scope']})
    else:
        raise ValueError("unsupported research benchmark: " + template_id)
    statuses = {check["status"] for check in checks}
    overall = "fail" if "fail" in statuses else "insufficient" if "insufficient" in statuses else "pass"
    return {"schema": 1, "template_id": template_id, "overall": overall, "checks": checks,
            "qualification": "comparison only; pass does not replace mesh, boundary, material and fixture convergence evidence"}
