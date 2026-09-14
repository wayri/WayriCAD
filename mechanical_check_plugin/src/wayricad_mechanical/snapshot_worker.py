import json
import sys
from pathlib import Path
from .extract import prepare_file

if __name__ == '__main__':
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    data = prepare_file(request['board_path'], request['workdir'], request['config'], request['project_dir'])
    (Path(request['workdir']) / 'board.json').write_text(json.dumps(data), encoding='utf-8')

