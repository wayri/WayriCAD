from types import SimpleNamespace

from harness_workbench_plugin.overview import overview_state


def record(project, connector):
    return SimpleNamespace(project=project, connector=connector)


def link(status="linked"):
    return SimpleNamespace(status=status)


def test_overview_progresses_from_import_to_review():
    assert overview_state([], [], [])["next_step"] == "Import pin documents"
    records = [record("A", "J1"), record("A", "J1"), record("B", "J2")]
    sourced = overview_state(records, [], [])
    assert (sourced["projects"], sourced["connectors"], sourced["stage"]) == (2, 2, 1)
    unresolved = overview_state(records, [link(), link("unmatched")], [])
    assert unresolved["unresolved"] == 1
    assert unresolved["next_step"] == "Review unresolved wires"
    ready = overview_state(records, [link()], [object(), object()])
    assert (ready["wires"], ready["paths"], ready["stage"]) == (1, 2, 3)
    assert ready["next_step"] == "Review draft and export"
