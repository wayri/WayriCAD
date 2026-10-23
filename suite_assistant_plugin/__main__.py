"""Expose the same local planner and execution commands without a GUI."""
from wayricad_runtime.assistant import main

if __name__ == '__main__':
    raise SystemExit(main())
