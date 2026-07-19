# __main__.py
"""
Entry point for running the CLI as a module.

Usage:
    python -m extract_pins_plugin <command> [options] <pcb_file>
"""

import sys

from .cli import main

if __name__ == '__main__':
    sys.exit(main())
