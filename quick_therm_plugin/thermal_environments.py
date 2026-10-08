"""Explicit equivalent board boundaries; no airflow or enclosure CFD is implied."""
import math

ENVIRONMENTS = ("air", "vacuum", "forced_air", "potting", "sealed")

def boundary_settings(environment, settings):
    """Return validated surface coefficients and their declared assumptions.

    Potting is a one-dimensional coating resistance to a fixed external ambient.
    Sealed uses entered effective heat transfer to a fixed enclosure temperature.
    Neither predicts cavity air temperature or an enclosure heating transient.
    """
    if environment not in ENVIRONMENTS:
        raise ValueError("Unsupported thermal environment: " + str(environment))
    values = dict(settings)
    def positive(key, allow_zero=False):
        try:
            value = float(values[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Enter explicit " + key) from exc
        if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
            raise ValueError(key + " must be finite and positive.")
        return value
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
            values["ambient_c"] = float(values["enclosure_temperature_c"])
            if not math.isfinite(values["ambient_c"]) or values["ambient_c"] <= -273.15:
                raise ValueError("Enter physical enclosure_temperature_c.")
            notes.append("Sealed enclosure is a fixed-temperature effective boundary; cavity airflow and enclosure thermal capacity are not solved.")
        else:
            notes.append("Forced airflow uses explicitly entered heat-transfer coefficients, not a computed flow field.")
    elif environment == "potting":
        k = positive("potting_k_w_mk")
        thickness = positive("potting_thickness_mm") * 1e-3
        outer_h = positive("potting_outer_h_w_m2k")
        values["board_h_w_m2k"] = 1 / (thickness/k + 1/outer_h)
        values.setdefault("sink_h_w_m2k", values["board_h_w_m2k"])
        values["board_emissivity"] = 0
        notes.append("Potting is a uniform one-dimensional coating resistance in series with entered external convection; coating heat storage, lateral spreading and radiation are unresolved.")
    return values, notes
