"""Private standalone entry point for the KiCad-bundled native runtime."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wayri_variants.gui import launch

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='')
    launch(parser.parse_args().project)
