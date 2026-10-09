"""Explicit equivalent board boundaries; no airflow or enclosure CFD is implied."""
import math
from collections.abc import Mapping

ENVIRONMENTS = ("air", "vacuum", "forced_air", "potting", "sealed")

def boundary_settings(environment, settings):
    """Return validated surface coefficients and their declared assumptions.

    Potting is a one-dimensional coating resistance to a fixed external ambient.
    Sealed uses entered effective heat transfer to a fixed enclosure temperature.
    Neither predicts cavity air temperature or an enclosure heating transient.
    """
    if environment not in ENVIRONMENTS:
        raise ValueError("Unsupported thermal environment: " + str(environment))
    if not isinstance(settings, Mapping):
        raise ValueError("Thermal environment settings must be a mapping.")
    values = dict(settings)
    def positive(key, allow_zero=False):
        try:
            raw = values[key]
            if isinstance(raw, bool):
                raise ValueError(key + " must be a number, not a boolean.")
            value = float(raw)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Enter explicit " + key) from exc
        if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
            raise ValueError(key + " must be finite and positive.")
        return value
    for key in ("board_airflow_m_s", "sink_airflow_m_s", "board_h_w_m2k", "sink_h_w_m2k"):
        if key in values:
            values[key] = positive(key, allow_zero=True)
    for key in ("board_emissivity", "sink_emissivity"):
        if key in values:
            raw = values[key]
            entries = raw.items() if isinstance(raw, Mapping) and key == "sink_emissivity" else [(None, raw)]
            normalized = {}
            for reference, entry in entries:
                try:
                    if isinstance(entry, bool):
                        raise ValueError()
                    number = float(entry)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(key + " requires finite emissivity between zero and one.") from exc
                if not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError(key + " requires finite emissivity between zero and one.")
                normalized[reference] = number
            values[key] = normalized if isinstance(raw, Mapping) else normalized[None]
    notes = []
    if environment == "vacuum":
        for key in ("board_airflow_m_s", "sink_airflow_m_s", "board_h_w_m2k", "sink_h_w_m2k"):
            if float(values.get(key, 0)) != 0:
                raise ValueError("Vacuum requires zero airflow and convection.")
        values.update(board_h_w_m2k=0, sink_h_w_m2k=0)
    elif environment in ("forced_air", "sealed"):
        values["board_h_w_m2k"] = positive("board_h_w_m2k")
        values.setdefault("sink_h_w_m2k", values["board_h_w_m2k"])
        if environment == "sealed":
            raw = values.get("enclosure_temperature_c")
            try:
                if isinstance(raw, bool):
                    raise ValueError()
                values["ambient_c"] = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Enter physical enclosure_temperature_c.") from exc
            if not math.isfinite(values["ambient_c"]) or values["ambient_c"] <= -273.15:
                raise ValueError("Enter physical enclosure_temperature_c.")
            notes.append("Sealed enclosure is a fixed-temperature effective boundary; cavity airflow and enclosure thermal capacity are not solved.")
        else:
            notes.append("Forced airflow uses explicitly entered heat-transfer coefficients, not a computed flow field.")
    elif environment == "potting":
        k = positive("potting_k_w_mk")
        thickness = positive("potting_thickness_mm") * 1e-3
        outer_h = positive("potting_outer_h_w_m2k")
        effective_h = 1 / (thickness/k + 1/outer_h)
        if not math.isfinite(effective_h) or effective_h <= 0:
            raise ValueError("Potting thermal resistance exceeds the finite numerical range.")
        values["board_h_w_m2k"] = effective_h
        values.setdefault("sink_h_w_m2k", values["board_h_w_m2k"])
        values["board_emissivity"] = 0
        notes.append("Potting is a uniform one-dimensional coating resistance in series with entered external convection; coating heat storage, lateral spreading and radiation are unresolved.")
    return values, notes
