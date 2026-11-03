"""Dedicated DFM/DFA IPC action; existing manufacturing releases stay separate."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if not (ROOT / 'wayricad_runtime').is_dir():
    sys.path.insert(0, str(ROOT.parent))


def main():
    from wayricad_runtime.bootstrap import relaunch, failure
    from wayricad_runtime.loading import LoadingWindow
    loading = LoadingWindow('WayriCAD DFM / DFA Studio')
    try:
        status = relaunch(ROOT, 'dfm_entrypoint.py', profile='ipc', loading=loading)
        if status is not None:
            return status
        from wayricad_runtime.native_analysis import launch
        loading.finish(); loading = None
        return launch(ROOT, 'manufacturing_readiness_plugin')
    except Exception as exc:
        return failure(exc, 'WayriCAD DFM / DFA Studio')
    finally:
        if loading:
            loading.finish()


if __name__ == '__main__':
    raise SystemExit(main())
