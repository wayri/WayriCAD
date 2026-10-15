"""Disposable native validator process; never edits the originating editor."""
import json
from pathlib import Path
import sys


def main():
    import pcbnew as api
    # Works both in a source tree and an independently extracted PCM package.
    import importlib.util
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('trace_refiner_worker',root/'__init__.py',submodule_search_locations=[str(root)])
    package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
    from trace_refiner_worker.refiner import Change,Plan,snapshot,rule_hash,validate,native_rules
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));result=Path(sys.argv[2])
    try:
        board=api.LoadBoard(request['board'])
        manager=api.SETTINGS_MANAGER();project=str(Path(request['board']).with_suffix('.kicad_pro'))
        manager.LoadProject(project,False);board.SetProject(manager.GetProject(project))
        saved=native_rules(board);live=request['rules']
        if json.loads(json.dumps(saved))!=live:raise ValueError('Live Board Setup differs from the saved project. Save Board Setup and preview again.')
        # Strengthen only the disposable DRC context. KiCad 10 SWIG does not
        # expose severity values safely; disabled copper checks must not hide
        # a new collision. The originating project file is never changed.
        project_path=Path(project);context=json.loads(project_path.read_text(encoding='utf-8'))
        severities=context.setdefault('board',{}).setdefault('design_settings',{}).setdefault('rule_severities',{})
        for key in ('clearance','shorting_items','tracks_crossing','track_width',
                    'track_angle','track_segment_length','copper_edge_clearance',
                    'hole_clearance','hole_to_hole','holes_co_located','via_diameter',
                    'annular_width','drill_out_of_range','isolated_copper',
                    'starved_thermal','zones_intersect'):
            severities[key]='error'
        project_path.write_text(json.dumps(context),encoding='utf-8')
        by_id={t.m_Uuid.AsString():t for t in board.GetTracks()}
        changes=[Change([by_id[i] for i in c['ids']],c['before'],c['after'],c['net'],c['layer'],c['width']) for c in request['changes']]
        review=Plan(snapshot(board,api),rule_hash(board),request['settings'],changes)
        validate(board,api,review,evidence_dir=request.get('evidence_dir'))
        result.write_text(json.dumps(dict(validated=True,evidence=review.evidence)),encoding='utf-8')
    except Exception as exc:
        result.write_text(json.dumps(dict(validated=False,error=str(exc))),encoding='utf-8');return 1
    return 0


if __name__=='__main__':
    # KiCad's embedded project globals have native process-lifetime ownership.
    # Results are closed/flushed by main; bypass unsafe SWIG shutdown ordering
    # in this disposable child, never in the PCB Editor.
    import os
    os._exit(main())
