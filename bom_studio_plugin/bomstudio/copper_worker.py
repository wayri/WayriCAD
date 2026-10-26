"""Private process entry point; never edits the input PCB."""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bomstudio.board_analytics import analyze_saved_board


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));path=Path(request['board'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=request['sha256']:raise ValueError('PCB changed before analysis.')
    report=analyze_saved_board(path)
    if report.get('status')=='unavailable':raise ValueError(report.get('source',{}).get('error') or '; '.join(report.get('warnings',[])) or 'Copper geometry unavailable.')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=request['sha256']:raise ValueError('PCB changed during analysis.')
    Path(sys.argv[2]).write_text(json.dumps(report,allow_nan=False),encoding='utf-8')


if __name__=='__main__':
    try:main()
    except Exception as error:print(str(error),file=sys.stderr);raise SystemExit(1)
