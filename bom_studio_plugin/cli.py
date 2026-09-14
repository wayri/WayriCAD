#!/usr/bin/env python3
"""Location-independent CLI entry point; does not launch the GUI unless asked."""
from bomstudio.cli import main
if __name__=='__main__':raise SystemExit(main())
