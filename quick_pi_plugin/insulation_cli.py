"""Screen saved multi-net results without rerunning or editing board copper."""
import hashlib
import json


def run(args, argv):
    from .insulation_screen import screen
    from wayricad_runtime.report_ui import publish_documents
    options={word.split('=')[0] for word in argv if word.startswith('--')}
    if args.board or options-{'--insulation-result','--insulation-policy','--output'}:
        raise ValueError('Screening accepts only saved multi-net results, explicit policy and optional --output.')
    if not args.insulation_result or not args.insulation_policy:
        raise ValueError('Provide both --insulation-result and --insulation-policy.')
    sources=[args.insulation_result,args.insulation_policy]
    raw=[]
    for path,limit in zip(sources,[128*1024*1024,1024*1024]):
        if path.stat().st_size>limit:raise ValueError('Screening input exceeds its size budget.')
        raw.append(path.read_bytes())
    def invalid(value):raise ValueError('Non-finite JSON input: '+value)
    report=screen(*[json.loads(value,parse_constant=invalid) for value in raw])
    report['input_sha256']=[hashlib.sha256(value).hexdigest() for value in raw]
    if any(path.read_bytes()!=value for path,value in zip(sources,raw)):
        raise ValueError('Screening input changed; discard this result.')
    text=json.dumps(report,indent=2,allow_nan=False)+'\n'
    if args.output:
        if args.output.suffix.lower()!='.json':raise ValueError('Screening output requires .json.')
        publish_documents({args.output:text},sources=sources)
    print(text,end='')
    return 0 if report['status']=='SCREENED' else 3
