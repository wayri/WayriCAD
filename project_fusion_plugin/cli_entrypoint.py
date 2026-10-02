"""Standalone runner without importing KiCad's action-registration initializer."""
import importlib
from pathlib import Path
import sys
import types

if __name__=='__main__':
    package=types.ModuleType('_fusion_cli')
    package.__path__=[str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__]=package
    raise SystemExit(importlib.import_module(package.__name__+'.__main__').main())
