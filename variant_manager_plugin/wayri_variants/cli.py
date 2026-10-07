"""Command-line interface. Mutations preview by default, never auto-apply."""
from __future__ import annotations
import argparse
import json
import sys
from . import service as S


def parser():
    p = argparse.ArgumentParser(description='WayriCAD Variant Manager â€” native KiCad 10 variants')
    sub = p.add_subparsers(dest='command')
    gui = sub.add_parser('gui', help='Open the native desktop interface')
    gui.add_argument('--project', default='')
    gui.add_argument('--note', default='')
    for name, help_text in [('list', 'List saved native variants'), ('backups', 'List verified local backups')]:
        s = sub.add_parser(name, help=help_text)
        s.add_argument('project')
    b = sub.add_parser('backup', help='Create an immutable, verified source + variant ZIP')
    b.add_argument('project'); b.add_argument('--output'); b.add_argument('--editors-closed', action='store_true')
    v = sub.add_parser('verify-backup', help='Verify ZIP structure, sizes, and checksums without extracting')
    v.add_argument('archive')
    job = sub.add_parser('job', help='Preview a JSON operation list or apply with verified backup')
    job.add_argument('project'); job.add_argument('operations')
    job.add_argument('--apply', action='store_true')
    job.add_argument('--editors-closed', action='store_true')
    job.add_argument('--yes', action='store_true')
    operations = {}
    for name, help_text in [('set-default', 'Promote a named variant; preserve surviving variants'),
                            ('delete', 'Delete several named variants in one reviewed transaction'),
                            ('restore-variants', 'Restore selected variants, not drawing geometry'),
                            ('restore-sources', 'Restore whole source files; rewinds later design edits')]:
        s = sub.add_parser(name, help=help_text)
        s.add_argument('project')
        s.add_argument('--apply', action='store_true', help='Apply, rather than only preview')
        s.add_argument('--editors-closed', action='store_true', help='Confirm all project editors and manager are closed')
        s.add_argument('--yes', action='store_true', help='Explicitly accept this operation for unattended use')
        s.add_argument('--save-review', metavar='NEW_FILE', help='Save review to a new text file; never overwrite')
        operations[name] = s
    s = operations['set-default']; s.add_argument('variant')
    s.add_argument('--remove-source', action='store_true', help='Remove source name after promoting it; default keeps it')
    s.add_argument('--preserve-old', metavar='NEW_NAME', help='Also retain the old Default under this new name')
    operations['delete'].add_argument('variants', nargs='+')
    s = operations['restore-variants']; s.add_argument('archive'); s.add_argument('variants', nargs='+')
    s.add_argument('--overwrite', action='store_true', help='Explicitly replace existing selected variant names')
    operations['restore-sources'].add_argument('archive')
    return p


def main(argv=None) -> int:
    p = parser(); args = p.parse_args(argv)
    try:
        if args.command in (None, 'gui'):
            from .gui import launch
            launch(getattr(args, 'project', ''), getattr(args, 'note', ''))
            return 0
        if args.command == 'list':
            print(json.dumps(S.inventory(args.project), indent=2, ensure_ascii=False))
            return 0
        if args.command == 'backups':
            print(json.dumps(S.list_backups(args.project), indent=2, ensure_ascii=False, default=str)); return 0
        if args.command == 'backup':
            print(S.create_backup(args.project, destination=args.output, editors_closed=args.editors_closed)); return 0
        if args.command == 'verify-backup':
            manifest, semantic, _ = S.read_backup(args.archive)
            print(json.dumps({'verified': True, 'root': manifest['root'], 'variants': semantic['names'],
                              'files': len(manifest['files']), 'reason': manifest['reason']}, indent=2, ensure_ascii=False)); return 0
        if args.command == 'job':
            from pathlib import Path
            plan = S.preview(args.project, json.loads(Path(args.operations).read_text(encoding='utf-8')))
            print(json.dumps(S.review(plan), indent=2, ensure_ascii=False))
            if args.apply:
                if not args.yes or not args.editors_closed:
                    raise S.Error('Applying requires --yes and --editors-closed.')
                print(json.dumps({'backup': str(S.apply(plan, editors_closed=True))}))
            return 0
        if args.command == 'set-default':
            plan = S.plan_default(args.project, args.variant, keep_source=not args.remove_source, preserve_old=args.preserve_old)
        elif args.command == 'delete':
            plan = S.plan_delete(args.project, args.variants)
        elif args.command == 'restore-variants':
            plan = S.plan_restore_variants(args.project, args.archive, args.variants, overwrite=args.overwrite)
        elif args.command == 'restore-sources':
            plan = S.plan_restore_sources(args.project, args.archive)
        else:
            p.error('Unknown command')
        review = plan.title + '\n\n' + '\n'.join(plan.summary) + '\n\n' + plan.diff
        print(review)
        if args.save_review:
            with open(args.save_review, 'x', encoding='utf-8') as stream:
                stream.write(review)
        if not args.apply:
            print('\nPREVIEW ONLY â€” project files were not changed. Applying requires --apply --editors-closed --yes.')
            return 0
        if not args.yes or not args.editors_closed:
            raise S.Error('Applying requires BOTH --yes and --editors-closed. No project files written.')
        backup = S.apply(plan, editors_closed=True)
        print('\nApplied. Recovery backup:', backup or 'No changes required.')
        print('Reopen KiCad; after variant edits, review Update PCB from Schematic before producing outputs.')
        return 0
    except (S.Error, OSError, ValueError, ImportError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrupted. Inspect the project and any recovery backup before retrying.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
