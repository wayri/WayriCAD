"""Large report payloads shrink without changing any exact saved values."""
import base64
import gzip
import json
import re
import shutil
import subprocess

import pytest

from wayricad_runtime.report_data import script_json


def test_small_payload_stays_synchronous_and_script_safe():
    expression,asynchronous=script_json({'net':'</script><script>bad()</script>','value':None})
    assert not asynchronous and '<' not in expression
    assert json.loads(expression)['value'] is None


def test_large_payload_is_exact_deterministic_and_much_smaller():
    payload={'net':'/Supply → Load','samples':[[i/7,0.12345678901234567,None] for i in range(15000)]}
    expression,asynchronous=script_json(payload)
    assert asynchronous
    encoded=re.search(r'atob\("([A-Za-z0-9+/=]+)"\)',expression)[1]
    assert json.loads(gzip.decompress(base64.b64decode(encoded)))==payload
    assert len(expression)<len(json.dumps(payload))*.3
    assert script_json(payload)==(expression,asynchronous)


def test_browser_standard_decoder_retains_exact_samples_and_nulls():
    node=shutil.which('node')
    if not node:pytest.skip('Node required for browser-standard decompression check')
    payload={'samples':[[0.12345678901234567,None,'Ω']] * 10000}
    expression,_=script_json(payload)
    code='(async()=>{const value='+expression+';process.stdout.write(JSON.stringify(value));})().catch(e=>{console.error(e);process.exit(1)});'
    result=subprocess.run([node,'-e',code],stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',check=True,timeout=15)
    assert json.loads(result.stdout)==payload
