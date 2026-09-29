"""Make the public QuickTherm demonstration from the repository's PCB fixture."""

from pathlib import Path

import pcbnew


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "mechanical_check_plugin/tests/fixtures/validation-fixture.kicad_pcb"
    target = Path(__file__).with_name("thermal-demo.kicad_pcb")
    board = pcbnew.LoadBoard(str(source))
    examples = {"C1": ("0.20 W", "45 K/W"),
                "C2": ("0.45 W", "35 K/W"),
                "C3": ("0.10 W", "65 K/W"),
                "J1": ("0.30 W", "50 K/W")}
    positions = {"C1": (17, 30), "C2": (47, 10), "C3": (45, 30)}
    board_resistance = {"C1": "15 K/W", "C2": "12 K/W",
                        "C3": "20 K/W", "J1": "18 K/W"}
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        if reference in examples:
            power, resistance = examples[reference]
            footprint.SetField("Power_W", power)
            footprint.SetField("RthetaJA", resistance)
            footprint.SetField("RthetaJB", board_resistance[reference])
            footprint.SetField("Tmin_C", "0 °C")
            footprint.SetField("Tmax_C", "60 °C" if reference == "J1" else "80 °C")
        if reference in positions:
            x, y = positions[reference]
            footprint.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    pcbnew.SaveBoard(str(target), board)
    for suffix in (".kicad_prl", ".kicad_pro"):
        generated = target.with_suffix(suffix)
        if generated.is_file():
            generated.unlink()
    print(target)


if __name__ == "__main__":
    main()
