"""Subprocess entry point shared by source and installed desktop launchers."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
