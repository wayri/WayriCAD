"""Read-only inference and validation of reviewed power-intent documents."""
import json
from pathlib import Path


def run(args, argv):
    from .power_tree import infer_power_tree, load_power_tree
    from wayricad_runtime.report_ui import publish_documents
    options={word.split('=')[0] for word in argv if word.startswith('--')}
    if options-{'--power-tree','--infer-power-tree','--output','--timeout'}:
        raise ValueError('Power tree accepts only its mode, optional board, --output and --timeout.')
    if bool(args.power_tree)==bool(args.infer_power_tree):
        raise ValueError('Choose --power-tree or --infer-power-tree.')
    protected=[]
    if args.infer_power_tree:
        if not args.board:raise ValueError('Inference needs a saved board.')
        from .service import run_job
        source=Path(args.board).resolve(); protected.append(source)
        inventory=run_job({'action':'inspect','board_path':str(source)},timeout=args.timeout)
        tree=infer_power_tree(inventory,{'board_path':str(source),
                                       'source_sha256':inventory['source_sha256']})
    else:
        if args.board:raise ValueError('Document validation does not accept a board; use inference for a new board draft.')
        protected.append(args.power_tree.resolve())
        tree=load_power_tree(args.power_tree)
    source=tree.get('source',{})
    protected.extend(source[key] for key in ('board_path','study_input_path','source_path') if source.get(key))
    text=json.dumps(tree,indent=2,allow_nan=False)+'\n'
    if args.output:
        if args.output.suffix.lower()!='.json':raise ValueError('Power tree output must be .json.')
        publish_documents({args.output:text},sources=protected)
    print(text,end='')
    return 0
