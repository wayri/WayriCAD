"""Opt-in live local-model -> reviewed RLC tool -> explanation acceptance check."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wayricad_runtime import assistant, assistant_ollama


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--ollama-url', default=assistant_ollama.DEFAULT_URL)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--review-proposal', type=Path,
                        help='Replay a saved model proposal with the fixed documented fixture corrections.')
    args = parser.parse_args()
    query = 'Calculate microstrip impedance width 0.2 mm height 0.1 mm er 4.2'
    plan = (json.loads(args.review_proposal.read_text(encoding='utf-8')) if args.review_proposal else
            assistant_ollama.propose(query, model=args.model, url=args.ollama_url, timeout=args.timeout))
    expected = dict(topology='microstrip', width_mm=.2, height_mm=.1, er=4.2)
    exact = (len(plan['steps']) == 1 and plan['steps'][0]['action'] == 'trace-impedance.cross-section'
             and plan['steps'][0]['params'] == expected)
    if args.review_proposal:
        assistant.validate_plan(plan)
        if plan['query'] != query or plan.get('interpretation',{}).get('model') != args.model:
            raise ValueError('Not the expected model/fixture request.')
        original_hash = plan['plan_hash']
        provenance = dict(plan['interpretation'])
        plan = assistant.propose(query, tasks=[dict(action='trace-impedance.cross-section',params=expected)])
        plan['interpretation'] = dict(provenance, original_plan_hash=original_hash,
            scope_reviewed=True, review='Explicit fixed test-fixture correction; not autonomous LLM accuracy.')
        plan = assistant._seal(plan)
    args.output_root.mkdir(parents=True, exist_ok=True)
    assistant._write_new(args.output_root / ('proposal-' + plan['plan_hash'] + '.json'), plan)
    if (len(plan['steps']) != 1 or plan['steps'][0]['action'] != 'trace-impedance.cross-section'):
        raise ValueError('Model selected unexpected actions; nothing executed: ' +
                         json.dumps(plan['steps']))
    if plan['steps'][0]['params'] != expected:
        raise ValueError('Model changed or omitted expected inputs; nothing executed.')
    assistant.validate_plan(plan)
    result = assistant.run_plan(plan, args.output_root, timeout_seconds=30)
    if result['status'] != 'completed':
        raise ValueError('Deterministic tool did not complete.')
    explanation = assistant_ollama.explain(result, result['output_dir'], model=args.model,
        url=args.ollama_url, timeout=args.timeout)
    path = Path(result['output_dir'])/'ollama-explanation.json'
    assistant._write_new(path, explanation)
    print(json.dumps(dict(status='PASS', model=args.model, plan_hash=plan['plan_hash'],
        original_proposal_exact=exact, fixture_reviewed=bool(args.review_proposal),
        actions=len(assistant.capabilities()['actions']), result_dir=result['output_dir'],
        explanation=str(path), host_status=explanation['host_status']), indent=2))


if __name__ == '__main__':
    main()
