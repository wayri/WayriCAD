"""Revision binding includes recursive and flat saved schematic inputs."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from wayricad_runtime import assistant


def schematic(path, *children):
    path.parent.mkdir(parents=True, exist_ok=True)
    body=''.join('(sheet (property "Sheetfile" '+json.dumps(str(child))+'))' for child in children)
    path.write_text('(kicad_sch '+body+')', encoding='utf-8')
    return path


def source_paths(context, inputs=()):
    return {Path(p) for p in assistant._source_paths(context,[{'input_files':list(inputs)}])}


def test_recursive_reused_and_cyclic_sheets_and_companions_are_bound(tmp_path):
    board=tmp_path/'board.kicad_pcb';board.write_text('saved PCB')
    project=tmp_path/'board.kicad_pro';project.write_text('{}')
    rules=tmp_path/'board.kicad_dru';rules.write_text('(version 1)')
    root=schematic(tmp_path/'board.kicad_sch','sheets/child.kicad_sch','sheets/child.kicad_sch')
    child=schematic(tmp_path/'sheets/child.kicad_sch','../board.kicad_sch','grand.kicad_sch')
    grand=schematic(tmp_path/'sheets/grand.kicad_sch')
    assert source_paths({'board':str(board)})=={board,project,rules,root,child,grand}


def test_flat_top_level_sheets_and_environment_expansion(tmp_path,monkeypatch):
    root=tmp_path/'project';root.mkdir()
    external=schematic(tmp_path/'external/flat.kicad_sch')
    monkeypatch.setenv('ASSISTANT_TEST_SHEETS',str(external.parent))
    local=schematic(root/'local.kicad_sch')
    project=root/'design.kicad_pro'
    project.write_text(json.dumps({'schematic':{'top_level_sheets':[
        {'filename':'${KIPRJMOD}/local.kicad_sch'},
        {'filename':'${ASSISTANT_TEST_SHEETS}/flat.kicad_sch'}]}}))
    assert source_paths({'project':str(project)})=={project,local,external}


def test_project_variables_resolve_and_cannot_override_project_root(tmp_path):
    project=tmp_path/'design.kicad_pro'
    project.write_text(json.dumps({'text_variables':{'SUBDIR':'sheets','KIPRJMOD':'elsewhere'}}))
    root=schematic(tmp_path/'design.kicad_sch','${KIPRJMOD}/${SUBDIR}/child.kicad_sch')
    child=schematic(tmp_path/'sheets/child.kicad_sch')
    assert source_paths({},[str(project)])=={project,root,child}


def test_recursive_sheet_edit_invalidates_previously_ready_plan(tmp_path):
    project=tmp_path/'design.kicad_pro';project.write_text('{}')
    schematic(tmp_path/'design.kicad_sch','child.kicad_sch')
    child=schematic(tmp_path/'child.kicad_sch')
    plan=assistant.propose('list variants',{'project':str(project)}, {'action':'variant-manager.list'})
    assert plan['status']=='ready'
    assistant.validate_plan(plan)
    child.write_text('(kicad_sch (uuid changed))')
    with pytest.raises(ValueError,match='Saved inputs changed'):
        assistant.validate_plan(plan)


@pytest.mark.parametrize('reference', ['missing.kicad_sch','${ASSISTANT_NO_SUCH_VARIABLE}/child.kicad_sch','wrong.txt','kicad-embed:child.kicad_sch'])
def test_missing_or_unresolved_child_fails_closed(tmp_path,reference,monkeypatch):
    monkeypatch.delenv('ASSISTANT_NO_SUCH_VARIABLE',raising=False)
    root=schematic(tmp_path/'design.kicad_sch',reference)
    with pytest.raises(ValueError):source_paths({'schematic':str(root)})


def test_cyclic_environment_variables_fail_closed(tmp_path,monkeypatch):
    monkeypatch.setenv('ASSISTANT_FIRST','${ASSISTANT_SECOND}')
    monkeypatch.setenv('ASSISTANT_SECOND','${ASSISTANT_FIRST}')
    root=schematic(tmp_path/'design.kicad_sch','${ASSISTANT_FIRST}/child.kicad_sch')
    with pytest.raises(ValueError,match='Cyclic'):source_paths({'schematic':str(root)})


@pytest.mark.parametrize('document', [{'schematic':[]},{'schematic':{'top_level_sheets':'not an array'}},{'schematic':{'top_level_sheets':[{}]}}])
def test_malformed_project_hierarchy_fails_closed(tmp_path,document):
    project=tmp_path/'design.kicad_pro';project.write_text(json.dumps(document))
    with pytest.raises(ValueError):source_paths({'project':str(project)})


def test_source_count_is_bounded_before_traversal(tmp_path):
    paths=[schematic(tmp_path/f'sheet-{i}.kicad_sch') for i in range(301)]
    with pytest.raises(ValueError,match='300'):source_paths({},map(str,paths))


def test_combined_source_bytes_are_bounded(tmp_path):
    first=tmp_path/'first.txt';first.write_text('x'*70)
    second=tmp_path/'second.txt';second.write_text('x'*40)
    with patch.object(assistant,'MAX_SOURCE_BYTES',100),pytest.raises(ValueError,match='combined'):
        source_paths({},[str(first),str(second)])


def test_wrong_schematic_root_is_not_silently_ignored(tmp_path):
    root=tmp_path/'wrong.kicad_sch';root.write_text('(not_a_schematic)')
    with pytest.raises(ValueError,match='modern KiCad'):source_paths({'schematic':str(root)})
