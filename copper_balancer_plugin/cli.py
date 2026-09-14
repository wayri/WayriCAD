"""Console wrapper; --help works without KiCad installed."""
import sys


def main():
    if '--help' in sys.argv[1:] or '-h' in sys.argv[1:]:
        from .native_app import main as help_main
        return help_main()
    from .native_runner import launch
    return launch()


if __name__ == '__main__':
    raise SystemExit(main())
