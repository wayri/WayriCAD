"""File-only diagnostics: no dependency on a working Windows stderr handle."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile


class QuietFileHandler(RotatingFileHandler):
    def handleError(self, record):
        # A full/unavailable log disk must not fall back to a broken stderr.
        pass


def get_logger():
    logger = logging.getLogger('WayriCAD Embed3D')
    logger.propagate = False
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        roots = [Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.cache')))/'WayriCAD Embed3D',
                 Path(tempfile.gettempdir())/'WayriCAD Embed3D']
        for root in roots:
            try:
                root.mkdir(parents=True, exist_ok=True)
                handler = QuietFileHandler(root/'embed_3d_plugin.log', maxBytes=1000000, backupCount=2, encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                logger.addHandler(handler)
                logger.log_path = str(root/'embed_3d_plugin.log')
                break
            except OSError:
                continue
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
            logger.log_path = '(log file unavailable)'
    return logger
