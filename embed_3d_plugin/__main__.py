"""Dependency-free file-mode CLI. Run from the extracted source distribution."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .core import Planner
from .paths import Resolver
from .storage import embed_files, restore_files


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(prog='python -m embed_3d_plugin', description='KiCad design portability: embed, extract and separately relink verified assets.')
    parser.add_argument('action', choices=('scan', 'embed', 'restore', 'inspect-board', 'rebuild-library',
                          'extract-pcb', 'relink-pcb', 'extract-symbols', 'embed-symbols', 'relink-symbols'))
    parser.add_argument('path', type=Path, help='.kicad_mod, .pretty, .kicad_pcb, or restore manifest.json')
    parser.add_argument('--project', type=Path, help='Project directory for KIPRJMOD / relative paths')
    parser.add_argument('--var', action='append', default=[], metavar='NAME=FOLDER')
    parser.add_argument('--apply', action='store_true', help='Explicitly permit writes; otherwise dry run')
    parser.add_argument('--allow-partial', action='store_true', help='Permit unresolved models to remain external')
    parser.add_argument('--backup-dir', type=Path, help='Parent for .embed_3d_plugin-backups; default: project/source directory')
    parser.add_argument('--json', action='store_true', help='Print a machine-readable scan manifest')
    parser.add_argument('--output', type=Path, help='Asset destination for extract, or NEW design folder for embed/relink')
    parser.add_argument('--assets', type=Path, help='Existing extraction folder for separate relink')
    parser.add_argument('--nickname', help='New local library nickname')
    parser.add_argument('--models-only', action='store_true', help='PCB: extract/relink models without footprints')
    parser.add_argument('--footprints-only', action='store_true', help='PCB: extract/relink footprints without models')
    parser.add_argument('--include-external', action='store_true', help='PCB extraction: also copy resolved external models')
    parser.add_argument('--sheet-only', action='store_true', help='Schematic: process selected sheet without following child sheets')
    parser.add_argument('--include-unused', action='store_true', help='Include unused cached symbol definitions when extracting')
    parser.add_argument('--path-mode', choices=('relative','absolute'), default='relative')
    parser.add_argument('--prune', action='store_true', help='Relink: remove only redundant managed attachments; never native symbol caches')
    parser.add_argument('--local-links', action='store_true', help='Embed symbols: also create a local symbol library and relink to it')
    parser.add_argument('--supplied', type=Path, action='append', default=[], help='Embed symbols: additionally archive this .kicad_sym verbatim')
    parser.add_argument('--validate-cli', action='store_true', help='Schematic writes: require a local KiCad 10 CLI parser/netlist check')
    args = parser.parse_args(argv)
    try:
        path = args.path.resolve()
        if args.action in ('extract-pcb','relink-pcb','extract-symbols','embed-symbols','relink-symbols'):
            from .portability_io import load_extraction, saved_project_variables
            from .unbundle import extract_pcb, relink_pcb
            from .symbols import extract_symbols, embed_symbols, relink_symbols
            if not args.output: raise ValueError('Choose --output FOLDER (no writes without --apply)')
            if args.models_only and args.footprints_only: raise ValueError('Choose only one of --models-only and --footprints-only')
            values={}
            for item in args.var:
                if '=' not in item: raise ValueError('Use --var NAME=VALUE')
                name,value=item.split('=',1);values[name]=value
            check=None
            if args.validate_cli and args.apply:
                if args.action not in ('embed-symbols','relink-symbols'):
                    raise ValueError('--validate-cli applies only to schematic design writes')
                from .cli_validation import validate_schematic
                check=lambda stage:validate_schematic(stage/path.name)
            if args.action=='extract-pcb':
                plan=extract_pcb(path,args.output,footprints=not args.models_only,models=not args.footprints_only,
                        include_external=args.include_external,nickname=args.nickname or 'UnbundledFootprints',
                        resolver=Resolver(args.project or path.parent,{**saved_project_variables(path),**values}))
                report=plan.preview()
                if args.apply:plan.publish(args.output)
            elif args.action=='extract-symbols':
                plan=extract_symbols(path,follow=not args.sheet_only,nickname=args.nickname or 'UnbundledSymbols',
                        include_unused=args.include_unused,variables=values)
                report=plan.preview()
                if args.apply:plan.publish(args.output)
            elif args.action=='embed-symbols':
                report=embed_symbols(path,args.output,follow=not args.sheet_only,nickname=args.nickname or 'EmbeddedSymbols',
                        supplied=args.supplied,local_links=args.local_links,variables=values,
                        apply=args.apply,validate=check)
            else:
                if not args.assets: raise ValueError('Select --assets FOLDER containing a verified extraction')
                if args.action=='relink-pcb':
                    meta,_=load_extraction(args.assets,path)
                    report=relink_pcb(path,args.assets,args.output,
                        link_footprints=bool(meta.get('footprints')) and not args.models_only,
                        link_models=bool(meta.get('models')) and not args.footprints_only,
                        path_mode=args.path_mode,prune=args.prune,apply=args.apply)
                else:
                    report=relink_symbols(path,args.assets,args.output,path_mode=args.path_mode,
                                          prune=args.prune,apply=args.apply,validate=check)
            report['applied']=args.apply
            if args.json: print(json.dumps(report,indent=2,ensure_ascii=False))
            else:
                print(('Created: ' if args.apply else 'Preview: ')+str(args.output))
                for key in ('files','bytes','sheets','symbols','footprint_count'):
                    if key in report: print(key+': '+str(report[key]))
                for warning in report.get('warnings',[]): print('Review: '+warning)
                print('Source designs unchanged.' if args.apply else 'No files changed. Add --apply to write.')
                if args.action=='extract-pcb' and not args.models_only:
                    print('CLI footprint extraction uses embedded WayriCAD Embed3D archives. Use the GUI for native as-placed normalization.')
            return 0
        if args.action in ('inspect-board', 'rebuild-library'):
            from .board_package import recover, rebuild_library
            if path.suffix.lower() != '.kicad_pcb' or not path.is_file():
                raise ValueError('Choose a saved .kicad_pcb containing a WayriCAD Embed3D archive')
            if args.action == 'inspect-board':
                package = recover(path.read_text(encoding='utf-8'))
                if args.json:
                    print(json.dumps(package.manifest, indent=2, ensure_ascii=False))
                else:
                    print('%d archived footprint definitions in %s' % (len(package.library_files), package.library_name))
                    print('All archived footprint/model hashes verified. No files changed.')
            else:
                result = rebuild_library(path, project=args.project, apply=args.apply)
                if args.json:
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    print(('Rebuilt: ' if args.apply else 'Preview: ')+result['library'])
                    print('%d definitions, %d missing files, table change: %s' % (result['files'], result['new_files'], result['table_change']))
                    print('Reopen the KiCad project to reload its library table.' if args.apply else 'No files changed. Add --apply to rebuild.')
                    print('Pure-Python archive verification; native KiCad parsing/rendering is not run by this CLI.')
            return 0
        if args.action == 'restore':
            if not args.apply:
                raise ValueError('Restore requires --apply. Close the affected footprints in KiCad first.')
            count = restore_files(path)
            print('Restored %d file(s).' % count)
            return 0
        files = sorted(path.glob('*.kicad_mod')) if path.is_dir() and path.suffix.lower() == '.pretty' else [path]
        if not files or any(p.suffix.lower() != '.kicad_mod' or not p.is_file() for p in files):
            raise ValueError('Choose an existing .kicad_mod or a nonempty .pretty library')
        values = {}
        for variable in args.var:
            if '=' not in variable:
                raise ValueError('Use --var NAME=FOLDER')
            name, value = variable.split('=', 1)
            values[name] = value
        project = args.project.resolve() if args.project else None
        planner = Planner(Resolver(project, values))
        plans = []
        for file in files:
            file = file.resolve()
            plan = planner.scan(file.read_bytes().decode('utf-8'), file.stem, file.parent)
            plan.source_path = file
            plans.append(plan)
        if args.json:
            print(json.dumps({'codec': planner.codec.label, 'resolution': planner.resolver.diagnostics(), 'plans': [p.manifest() for p in plans]}, indent=2, ensure_ascii=False))
        else:
            print(planner.codec.label)
            for plan in plans:
                print('\n'+plan.name)
                for row in plan.rows:
                    print('  [%s] %s\n    %s' % (row.status, row.reference, row.detail))
        if args.action == 'embed' and args.apply:
            blocked = [r for p in plans for r in p.rows if not r.ready and r.status != 'Embedded']
            if blocked and not args.allow_partial:
                raise ValueError('Some models are unresolved. No files changed. Resolve paths or explicitly use --allow-partial.')
            if not any(p.actionable for p in plans):
                print('Nothing to embed; no files changed.')
                return 0
            backup = args.backup_dir or project or (path.parent if path.is_file() else path.parent)
            job = embed_files(plans, backup.resolve())
            print('\nEmbedded. Backups and original paths: '+str(job))
            print('File-mode validation only. Open the result in KiCad 10 to check rendering.')
        else:
            print('\nPreview only: no files changed. Use embed ... --apply to write with backups.')
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print('WayriCAD Embed3D: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
