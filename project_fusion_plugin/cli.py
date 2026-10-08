"""Saved-file Fusion workflows with reusable native-validated JSON plans.

Discovery needs no GUI. Preview creates detached candidates; applying to an
existing project requires closed-editor confirmation and preserves the backend's
source hashes, verified backups and rollback checks.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sys
import tempfile
from .model import MergeError, Options, SourceSpec


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _emit(value, output=None):
    text = json.dumps(value, indent=2, default=lambda obj: asdict(obj) if is_dataclass(obj) else str(obj))
    if output:
        path = Path(output).resolve()
        if isinstance(value, dict) and value.get('candidate_directory'):
            candidate = Path(value['candidate_directory']).resolve()
            if path == candidate or candidate in path.parents:
                raise MergeError('Save the JSON plan outside its candidate directory.')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            stream.write(text + '\n')
    print(text)


def _source(args):
    return SourceSpec(args.source, args.alias, variant=args.variant,
                      variant_mode=args.variant_mode, destination_variant=args.destination_variant)


def _guard(args, existing=False):
    if not args.apply or not args.yes:
        raise MergeError('Writing requires --apply --yes. Run the preview command first.')
    if existing and not args.editors_closed:
        raise MergeError('Save and close the destination KiCad editors, then use --editors-closed.')


def _options(path):
    data = _read(path)
    workspace = data.pop('_workspace', {})
    data['sources'] = [SourceSpec(**source) for source in data['sources']]
    return Options(**data), workspace


def _field_sources(specs):
    from .bom_fields import selected_sources
    return selected_sources(specs)


def _new_project(args, analyse_only=False):
    from . import engine, workspace as ws
    options, setup = _options(args.config)
    if args.cli_path:
        options.cli_path = args.cli_path
    if setup.get('import_into_existing'):
        raise MergeError('This setup targets an existing project; use import-preview --target instead.')
    include_layout = not args.schematic_only and setup.get('include_layout', True) is not False
    options.validate()
    if not analyse_only:
        _guard(args)
    parent = Path(options.destination).resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fusion-cli-', dir=parent) as folder:
        options.sources, originals = ws.materialize_sources(options.sources, include_layout, folder, options.cli_path)
        options._selection_originals = originals
        if include_layout:
            log = lambda msg: print(msg, file=sys.stderr)
            return engine.analyse(options, log)[2] if analyse_only else engine.merge(options, log)
        plan = ws.preview_new_schematic(options.sources, str(Path(folder) / 'candidate'), options.name,
                                        options.cli_path, options.gap_mm, options.copy_assets)
        plan['selection_originals'] = originals
        return plan['report'] if analyse_only else ws.publish_new_schematic(plan, options.destination, options.name)


def _dispatch(args):
    command = args.command
    if command == 'detect':
        from .source_detection import detect_source
        return [dict(asdict(choice), selection=choice.selection) for choice in detect_source(args.source)]
    if command == 'variants':
        from .variants import detect_variants
        return detect_variants(args.source)
    if command == 'sheets':
        from .sections import list_sections
        return list_sections(_source(args))
    if command == 'issues':
        from .merge_issues import scan_source
        return scan_source(_source(args))
    if command in {'fields', 'bom', 'fields-preview'}:
        from . import bom_fields as fields
        from .repair import fingerprint
        specs = _options(args.config)[0].sources
        sources = _field_sources(specs)
        rows = fields.inventory(sources)
        if command == 'fields-preview':
            edit = _read(args.edits)
            changes = fields.preview_fields(rows, edit['identities'], edit.get('edits'), edit.get('renames'))
            return {'cli_operation': 'fields', 'specs': [asdict(spec) for spec in specs],
                    'hashes': {str(source.project_file.parent): fingerprint(source.project_file.parent) for source in sources},
                    'file_hashes': {path: digest for source in sources for path, digest in source.hashes.items()},
                    'changes': changes}
        result = fields.grouped_bom(rows, args.include_excluded) if command == 'bom' else rows
        if args.csv:
            if Path(args.csv).exists():
                raise MergeError('CSV export already exists; choose a new file.')
            fields.export_csv(args.csv, result, bom=command == 'bom')
        return result
    if command == 'fields-apply':
        _guard(args)
        from .bom_fields import apply_to_copies, _check
        from .repair import fingerprint
        plan = _read(args.plan)
        if plan.get('cli_operation') != 'fields':
            raise MergeError('Use a JSON plan from fields-preview.')
        for root, hashes in plan['hashes'].items():
            if fingerprint(Path(root)) != hashes:
                raise MergeError('Source changed after field review; preview again.')
        _check(plan['file_hashes'])
        return apply_to_copies(_field_sources([SourceSpec(**spec) for spec in plan['specs']]), plan['changes'], args.destination)
    if command == 'dependencies-preview':
        from .dependencies import preview_dependencies
        return dict(preview_dependencies(_options(args.config)[0].sources), cli_operation='dependencies')
    if command == 'dependencies-apply':
        _guard(args)
        from .dependencies import apply_dependencies
        plan = _read(args.plan)
        if plan.get('cli_operation') != 'dependencies':
            raise MergeError('Use a JSON plan from dependencies-preview.')
        return apply_dependencies(plan, args.destination)
    if command in {'analyse', 'create'}:
        return _new_project(args, command == 'analyse')
    if command == 'import-preview':
        from .workspace import materialize_sources
        from .insertion import preview_import
        options, setup = _options(args.config)
        include_layout = not args.schematic_only and setup.get('include_layout', True) is not False
        parent = Path(args.candidate).resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        cli = args.cli_path or options.cli_path
        sources, originals = materialize_sources(options.sources, include_layout, parent, cli)
        plan = preview_import(args.target, sources, include_layout, args.candidate, cli, options.gap_mm, options.copy_assets)
        plan['selection_originals'] = originals
        return plan
    if command == 'layout-preview':
        from .board_layout import preview_layout_import
        return preview_layout_import(args.target, args.source, args.candidate, alias=args.alias,
                                     x_mm=args.x, y_mm=args.y, cli_path=args.cli_path)
    if command in {'links', 'scan-links', 'transactions'}:
        from . import linked_updates as linked
        if command == 'links':
            return linked.list_links(args.target, args.cli_path)
        if command == 'transactions':
            return linked.list_transactions(args.target)
        return linked.scan_links(args.target, args.cli_path, args.search_root,
                                 _read(args.source_overrides) if args.source_overrides else None)
    if command == 'update-preview':
        from .linked_updates import preview_update
        return preview_update(args.target, args.link, args.candidate, args.cli_path,
                              acknowledge_major=args.acknowledge_major,
                              source_overrides=_read(args.source_overrides) if args.source_overrides else None,
                              identity_overrides=_read(args.identity_overrides) if args.identity_overrides else None,
                              retain_destination_layout=args.retain_layout, layout_only=args.layout_only)
    if command in {'break-links-preview', 'adopt-links-preview', 'undo-preview'}:
        from . import linked_updates as linked
        if command == 'undo-preview':
            return linked.preview_undo(args.target, args.backup, args.candidate, args.cli_path)
        function = linked.preview_break_links if command == 'break-links-preview' else linked.preview_adopt_links
        return function(args.target, args.link, args.candidate, args.cli_path)
    if command == 'apply':
        _guard(args, existing=True)
        from .workspace import check_originals
        from .insertion import apply_import
        plan = _read(args.plan)
        check_originals(plan)
        return apply_import(plan)
    if command == 'section-preview':
        from .sections import preview_section, preview_schematic_sections
        if args.region:
            if len(args.sheet) != 1:
                raise MergeError('Routed section extraction requires one --sheet UUID path.')
            plan = preview_section(_source(args), args.sheet[0], args.region, args.cli_path, args.max_depth)
            plan['cli_operation'] = 'section'
        else:
            plan = preview_schematic_sections(_source(args), args.sheet, args.cli_path, args.max_depth, args.allow_root)
            plan['cli_operation'] = 'schematic-sections'
        return plan
    if command == 'section-apply':
        _guard(args)
        from .sections import apply_section, apply_schematic_sections
        plan = _read(args.plan)
        operation = plan.get('cli_operation')
        if operation not in {'section', 'schematic-sections'}:
            raise MergeError('Use a JSON plan from section-preview.')
        return (apply_section if operation == 'section' else apply_schematic_sections)(plan, args.destination)
    if command == 'repair-preview':
        from .repair import preview_repair
        plan = asdict(preview_repair(_source(args), args.cli_path, args.retain_blank,
                                    _read(args.resolutions) if args.resolutions else None))
        return dict(plan, cli_operation='repair', cli_path=args.cli_path)
    if command == 'repair-apply':
        _guard(args)
        from .repair import RepairPlan, apply_repair
        data = _read(args.plan)
        if data.pop('cli_operation', None) != 'repair':
            raise MergeError('Use a JSON plan from repair-preview.')
        cli = data.pop('cli_path', '')
        data['spec'] = SourceSpec(**data['spec'])
        return apply_repair(RepairPlan(**data), args.destination, cli)
    raise MergeError('Unknown command.')


def _parser():
    parser = argparse.ArgumentParser(description='WayriCAD Fusion: discover sources, preview changes and apply saved-file workflows.',
                                     epilog='Save previews with --output plan.json. Keep candidate folders until apply completes. Existing-project writes require --apply --yes --editors-closed.')
    parser.add_argument('--config', help='Legacy JSON setup (analyse/create are the explicit workflows)')
    parser.add_argument('--analyse', action='store_true', help='Legacy structural preflight')
    parser.add_argument('--gui', action='store_true', help='Open the native guided Fusion window')
    parser.add_argument('--cli-path', default='', help='Explicit kicad-cli executable')
    sub = parser.add_subparsers(dest='command')
    def add(name, help, source=False, target=False, candidate=False, write=False):
        p = sub.add_parser(name, help=help, description=help)
        p.add_argument('--output', help='Save JSON to a new file outside the candidate')
        if source:
            p.add_argument('source', help='Saved project, schematic or PCB path')
        if target:
            p.add_argument('--target', required=True, help='Working .kicad_pro path')
        if candidate:
            p.add_argument('--candidate', required=True, help='New detached candidate directory')
        if write:
            p.add_argument('--apply', action='store_true'); p.add_argument('--yes', action='store_true')
        p.add_argument('--cli-path', default='', help='Explicit kicad-cli executable (otherwise discovered)')
        return p
    def spec(p):
        p.add_argument('--alias', default='Source'); p.add_argument('--variant', default='<Default>')
        p.add_argument('--variant-mode', choices=('base', 'merge', 'separate'), default='base')
        p.add_argument('--destination-variant', default='<Default>')
    for name, help in [('detect','Classify source ownership and project/sheet/layout scope'), ('variants','List native source variants'), ('sheets','List exact sheet UUID occurrences'), ('issues','Scan source issues and repair choices')]:
        p = add(name, help, source=True)
        if name in {'sheets','issues'}:
            spec(p)
    for name in ('analyse','create'):
        p = add(name, 'Analyse a JSON setup' if name == 'analyse' else 'Create a native-validated new project', write=name == 'create')
        p.add_argument('--config', required=True, help='GUI Options JSON with source selection and variant handling')
        p.add_argument('--schematic-only', action='store_true')
    p = add('import-preview','Preview import into a working project', target=True, candidate=True)
    p.add_argument('--config', required=True); p.add_argument('--schematic-only', action='store_true')
    p = add('layout-preview','Preview isolated layout-only PCB import', source=True, target=True, candidate=True)
    p.add_argument('--alias', default='Layout'); p.add_argument('--x', type=float, default=20); p.add_argument('--y', type=float, default=20)
    for name in ('links','scan-links','transactions'):
        p = add(name, {'links':'List linked imports','scan-links':'Scan linked source changes','transactions':'List verified transaction backups'}[name], target=True)
        if name == 'scan-links':
            p.add_argument('--search-root', action='append'); p.add_argument('--source-overrides', help='JSON link-ID to source-path mapping')
    for name in ('update-preview','break-links-preview','adopt-links-preview','undo-preview'):
        p = add(name, 'Preview ' + name.removesuffix('-preview').replace('-', ' '), target=True, candidate=True)
        if name == 'undo-preview':
            p.add_argument('--backup', required=True)
        else:
            p.add_argument('--link', action='append', required=True, help='Exact link ID; repeat for bulk operations')
        if name == 'update-preview':
            p.add_argument('--acknowledge-major', action='store_true'); p.add_argument('--retain-layout', action='store_true'); p.add_argument('--layout-only', action='store_true')
            p.add_argument('--source-overrides'); p.add_argument('--identity-overrides')
    p = add('apply','Apply a reviewed existing-project import/update/link/undo JSON plan', write=True)
    p.add_argument('plan'); p.add_argument('--editors-closed', action='store_true')
    p = add('section-preview','Preview a routed rectangle or schematic-only sheet extraction', source=True); spec(p)
    p.add_argument('--sheet', required=True, action='append'); p.add_argument('--region', type=float, nargs=4, metavar=('X1','Y1','X2','Y2'))
    p.add_argument('--max-depth', type=int); p.add_argument('--allow-root', action='store_true')
    p = add('repair-preview','Preview source repair into a new copy', source=True); spec(p)
    p.add_argument('--retain-blank', action='store_true'); p.add_argument('--resolutions', help='JSON issue-ID to reviewed action mapping')
    for name in ('fields','bom','fields-preview','dependencies-preview'):
        p = add(name, {'fields':'Inspect source fields', 'bom':'Group selected source BOMs', 'fields-preview':'Preview identity-based field edits', 'dependencies-preview':'Audit dependencies and review safe path suggestions'}[name])
        p.add_argument('--config', required=True)
        if name == 'fields-preview':
            p.add_argument('--edits', required=True, help='JSON identities, edits and renames object')
        if name in {'fields','bom'}:
            p.add_argument('--csv', help='New CSV export file')
        if name == 'bom':
            p.add_argument('--include-excluded', action='store_true')
    for name in ('section-apply','repair-apply','fields-apply','dependencies-apply'):
        p = add(name, 'Publish a reviewed source copy without changing originals', write=True)
        p.add_argument('plan'); p.add_argument('--destination', required=True)
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.gui:
            import wx
            from .gui import FusionDialog
            app = wx.App(False)
            dialog = FusionDialog(None)
            try:
                dialog.ShowModal()
            finally:
                dialog.Destroy()
            return 0
        if args.command:
            result = _dispatch(args)
        elif args.config:
            # Existing automation keeps --config/--analyse compatibility; saved
            # options still require all source and outline acknowledgements.
            args.schematic_only = False; args.apply = True; args.yes = True
            result = _new_project(args, args.analyse)
        else:
            parser.error('Choose a command, --gui, or --config. Use --help for commands.')
        _emit(result, getattr(args, 'output', None))
        return 0
    except (MergeError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(f'Fusion stopped: {exc}', file=sys.stderr)
        return 2
