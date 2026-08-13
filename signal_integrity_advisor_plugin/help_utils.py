from pathlib import Path
import webbrowser

def open_help(_parent=None):
    webbrowser.open(Path(__file__).with_name("help.html").resolve().as_uri())

