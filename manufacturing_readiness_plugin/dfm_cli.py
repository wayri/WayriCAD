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
    reference = commands.add_parser('fab-reference', help='Export design IPC-D-356 plus a source-hash receipt using native KiCad; not CAM extraction')
    reference.add_argument('board', type=Path); reference.add_argument('output', type=Path)
    reference.add_argument('--cli', type=Path); reference.add_argument('--timeout', type=float, default=120)
    comparison = commands.add_parser('fab-compare', help='Compare exact terminal connectivity against imported CAM net groups for shorts and opens')
    comparison.add_argument('--reference', type=Path, required=True)
    comparison.add_argument('--cam', type=Path, required=True)
    comparison.add_argument('--confirm-independent-cam', action='store_true', help='Record operator review that observed connectivity was independently extracted from the fabrication job')
    for option in ('json', 'html', 'csv', 'text'):
        comparison.add_argument('--'+option, type=Path, help='Write the source-bound comparison report to this path')
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
        if args.command == 'fab-reference':
            from .fab_reference import export_reference
            receipt = export_reference(args.board, args.output, cli=args.cli, timeout_s=args.timeout)
            print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False)); return 0
        if args.command == 'fab-compare':
            from .fab_compare import load_netlist, compare_netlists
            from .fab_compare_report import source_snapshot, build_report, render_report, validate_report
            from .fab_reference import check_reference_receipt
            from wayricad_runtime.report_ui import publish_documents
            sources = [source_snapshot(args.reference, 'reference'), source_snapshot(args.cam, 'observed CAM')]
            binding = check_reference_receipt(args.reference)
            if binding.get('receipt_path'):
                receipt_source = source_snapshot(binding['receipt_path'], 'native receipt')
                if receipt_source['sha256'] != binding['receipt_sha256']:
                    raise ValueError('Native receipt changed during comparison; rerun.')
                sources.append(receipt_source)
            reference, observed = load_netlist(args.reference), load_netlist(args.cam)
            comparison = compare_netlists(reference, observed, confirm_independent_cam=args.confirm_independent_cam)
            comparison['reference_binding'] = binding
            report = build_report(comparison, sources=sources)
            documents = {}
            for name, extension in (('json', '.json'), ('html', '.html'), ('csv', '.csv'), ('text', '.txt')):
                destination = getattr(args, name)
                if destination is not None:
                    if destination.suffix.lower() != extension:
                        raise ValueError(f'--{name} requires a {extension} output filename.')
                    if destination.resolve() in {path.resolve() for path in documents}:
                        raise ValueError('Comparison report destinations must be distinct.')
                    documents[destination] = render_report(report, extension)
            if documents:
                publish_documents(documents, sources=[source['path'] for source in sources], source_guard=lambda: validate_report(report))
            print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
            return 1 if report['status'] == 'FAIL' else 0 if report['status'] == 'MATCH' else 3
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
    except (KeyboardInterrupt, InterruptedError):
        print(json.dumps(dict(error='Cancelled; no result accepted.')), file=sys.stderr); return 130
    except (ValueError, OSError, TypeError) as exc:
        print(json.dumps(dict(error=str(exc))), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
