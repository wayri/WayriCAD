"""Headless, source-bound vendor screening; no native GUI dependency."""
import argparse
import json
from pathlib import Path
import sys

from . import checklists
from .common_checklist import with_common_checks
from .dfm_checks import audit_snapshot
from .vendor_catalog import load_catalog, search_profiles


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('vendors', help='List bundled process profiles as JSON')
    listing.add_argument('--query', default=''); listing.add_argument('--layers', type=int)
    for name in ('preview', 'audit'):
        command = commands.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument('--profile'); source.add_argument('--profile-file', type=Path)
        command.add_argument('--context', required=True, help='Exact process context JSON; no inferred copper/material defaults')
        if name == 'audit':
            command.add_argument('board', type=Path)
            command.add_argument('--cli', type=Path)
            command.add_argument('--timeout', type=float, default=300)
            command.add_argument('--confirm-process', action='store_true', help='Confirm the selected process against the supplier quote')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        catalog = load_catalog()
        if args.command == 'vendors':
            result = search_profiles(catalog, args.query, layers=args.layers)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if len(args.context.encode('utf-8')) > checklists.MAX_DOCUMENT_BYTES:
            raise ValueError('Context exceeds the document size limit.')
        context = json.loads(args.context, object_pairs_hook=checklists._reject_duplicates)
        if args.profile_file:
            profile = checklists.load_profile(args.profile_file)
        else:
            profile = next((row for row in catalog['profiles'] if row['id'] == args.profile), None)
            if profile is None: raise ValueError('Unknown profile ID. Use the vendors command.')
        profile = with_common_checks(profile)
        preview = checklists.compile_native_rules(profile, context)
        if args.command == 'preview':
            print(json.dumps(preview, ensure_ascii=False, indent=2)); return 0
        if not args.confirm_process: raise ValueError('Supplier quote/process confirmation is required: --confirm-process')
        import math
        if not math.isfinite(args.timeout) or args.timeout <= 0: raise ValueError('Timeout must be positive and finite.')
        result = audit_snapshot(args.board, profile, context, cli=args.cli, timeout_s=args.timeout,
                                project_drc=not bool(preview['compiled_rule_ids']))
        result['profile'] = profile
        result['context'] = checklists.canonical_context(context)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        statuses = {row['status'] for row in result['results']}
        if 'FAIL' in statuses or not result['native']['clean']: return 1
        return 3 if 'UNKNOWN' in statuses else 0
    except KeyboardInterrupt:
        print(json.dumps(dict(error='Cancelled; no result accepted.')), file=sys.stderr); return 130
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps(dict(error=str(exc))), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
