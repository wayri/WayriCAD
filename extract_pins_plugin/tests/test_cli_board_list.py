"""Board component listing filters and serializes native KiCad library IDs."""

from __future__ import annotations

from extract_pins_plugin import cli


class FootprintID:
    def __init__(self, value: str) -> None:
        self.value = value

    def GetUniStringLibId(self) -> str:
        return self.value

    def __str__(self) -> str:
        return "<pcbnew.LIB_ID; proxy>"


class Footprint:
    def __init__(self, reference: str) -> None:
        self.reference = reference

    def GetReference(self) -> str:
        return self.reference

    def GetValue(self) -> str:
        return "Connector"

    def GetFPID(self) -> FootprintID:
        return FootprintID("Connector_Generic:Conn_01x02")

    def GetLayerName(self) -> str:
        return "F.Cu"


class Board:
    def GetFootprints(self) -> list[Footprint]:
        return [Footprint("C1"), Footprint("J2"), Footprint("J1")]


def test_board_list_filters_references_and_formats_footprint_id(monkeypatch):
    monkeypatch.setattr(cli, "load_board", lambda path: Board())
    captured = {}

    def capture(rows, format, output, title):
        captured["rows"] = rows
        return 0

    monkeypatch.setattr(cli, "write_rows", capture)
    assert cli.main(["board-list", "unused.kicad_pcb", "--refs", "j*", "--format", "json"]) == 0
    assert [row["Reference"] for row in captured["rows"]] == ["J1", "J2"]
    assert {row["Footprint"] for row in captured["rows"]} == {"Connector_Generic:Conn_01x02"}
