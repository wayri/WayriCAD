"""Packaged help stays in the native WayriCAD desktop."""
from pathlib import Path
from wayricad_runtime.help import open_help as show_help

def open_help(parent=None, filename="help.html"):
    return show_help(parent, Path(__file__).with_name(filename))
