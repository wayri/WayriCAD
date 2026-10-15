"""Measure display-only picking/rendering; optionally compare a source revision.

Run from the checkout with KiCad Python for --board, or ordinary Python for
synthetic geometry. No board writes, mesh changes or solver approximations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wayricad_runtime import board_render


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, help='Saved public/example PCB; requires native pcbnew')
    parser.add_argument('--baseline-ref', help='Trusted local Git revision to compare; e.g. c60e0ba0')
    parser.add_argument('--primitives', type=int, default=40000, help='Synthetic shape count')
    parser.add_argument('--queries', type=int, default=100)
    parser.add_argument('--plot-count', type=int, default=5000, help='Zero skips Matplotlib')
    parser.add_argument('--output', type=Path, help='New JSON result file; no overwrite')
    args = parser.parse_args(argv)
    if args.primitives < 1 or args.queries < 1 or args.plot_count < 0:
        parser.error('Counts must be positive; plot-count may be zero.')
    if args.output and args.output.exists():parser.error('Output already exists.')
    baseline = None
    if args.baseline_ref:
        code = subprocess.check_output(['git', 'show', args.baseline_ref+':wayricad_runtime/board_render.py'], cwd=ROOT)
        baseline = types.ModuleType('benchmark_baseline')
        exec(compile(code, 'benchmark_baseline.py', 'exec'), baseline.__dict__)
    before = None
    started = time.perf_counter()
    if args.board:
        import pcbnew
        before = hashlib.sha256(args.board.read_bytes()).hexdigest()
        scene = board_render.extract_board(pcbnew.LoadBoard(str(args.board.resolve())))
    else:
        rows = []
        for i in range(args.primitives):
            x, y = (i % 200)*1.5, (i//200)*1.5
            rows.append(dict(kind='polygon', role='track', layer=0, uuid=str(i), net='SIGNAL',
                             points=[[x,y],[x+1,y],[x+1,y+.2],[x,y+.2]], holes=[]))
        scene = board_render.prepare_scene(dict(primitives=rows, bounds=[0,0,300,max(1,args.primitives/200)*1.5]))
    result = dict(kind='display-only; not solver performance or accuracy',
                  primitives=len(scene['primitives']), extraction_s=time.perf_counter()-started,
                  python='.'.join(map(str, sys.version_info[:3])), platform=sys.platform)
    a, b, c, d = scene['bounds']
    queries = [(a+(c-a)*(i+.5)/args.queries, b+(d-b)*((i*7)%args.queries+.5)/args.queries)
               for i in range(args.queries)]
    reference = baseline.hit_test if baseline else board_render.hit_test
    started=time.perf_counter()
    expected=[reference(dict(scene), *point, [0]) for point in queries]
    result['reference_pick_s']=time.perf_counter()-started
    started=time.perf_counter();board_render.hit_test(scene,*queries[0],[0])
    result['index_build_s']=time.perf_counter()-started
    started=time.perf_counter()
    actual=[board_render.hit_test(scene,*point,[0]) for point in queries]
    result['indexed_pick_s']=time.perf_counter()-started
    if expected!=actual:raise AssertionError('Pick results changed.')
    result['identical_hits']=True;result['queries']=len(queries)
    if args.plot_count:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        subset=dict(primitives=scene['primitives'][:args.plot_count])
        methods=[('optimized',board_render.draw_matplotlib)]
        if baseline:methods.insert(0,('baseline',baseline.draw_matplotlib))
        for name, draw in methods:
            figure=Figure();canvas=FigureCanvasAgg(figure);axes=figure.add_subplot()
            started=time.perf_counter();artists=draw(axes,subset,[0]);axes.autoscale_view();canvas.draw()
            result[name+'_draw_s']=time.perf_counter()-started;result[name+'_artists']=len(artists)
    if args.board:
        if before!=hashlib.sha256(args.board.read_bytes()).hexdigest():raise AssertionError('Source changed.')
        result['source_sha256']=before;result['source_unchanged']=True
    rendered=json.dumps(result,indent=2)+'\n'
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream:stream.write(rendered)
    print(rendered,end='')


if __name__ == '__main__':
    main()
