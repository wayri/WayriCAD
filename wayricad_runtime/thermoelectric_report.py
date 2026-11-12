"""Offline Three.js volume/temperature preview with original-cell probing."""
import base64
from html import escape
import json
from pathlib import Path


def render_report(report):
    from .thermoelectric_study import validate_report
    validate_report(report)
    if not report.get('result',{}).get('converged'):raise ValueError('Only converged 3D evidence can be rendered.')
    folder=Path(__file__).with_name('assets')/'thermoelectric'
    core='data:text/javascript;base64,'+base64.b64encode((folder/'three.core.js').read_bytes()).decode()
    module=(folder/'three.module.js').read_text(encoding='utf-8').replace("'./three.core.js'",json.dumps(core))
    module='data:text/javascript;base64,'+base64.b64encode(module.encode()).decode()
    payload=json.dumps(report,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    template=(folder/'viewer.html').read_text(encoding='utf-8')
    return template.replace('__STUDY_JSON__',payload).replace('__THREE_MODULE__',module)
