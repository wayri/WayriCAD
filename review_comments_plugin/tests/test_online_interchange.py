"""Shared online KiView marker contracts; no provider traffic or vendor copy."""
import json
from itertools import product
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from review_comments_plugin.model import markdown, note, read_markers
from review_comments_plugin.canvas_model import markers_from_rows


def examples():
    for provider in ('github', 'gitlab'):
        for suffix, region in product(('pcb', 'sch'), (False, True)):
            target = dict(repository='example/controller', ref='a' * 40,
                          file=f'hardware/controller.kicad_{suffix}', kind='position',
                          reference='U1', netName='/Power/3V3', position=dict(x=12.5, y=8.25))
            if provider == 'gitlab':
                target.update(provider='gitlab', host='https://gitlab.example.org',
                              repository='team/hardware/controller')
            if region:
                target.pop('position')
                target.update(kind='region', area=dict(x=10, y=5, width=5, height=6.5))
            value = note('Check ΔV at U1 — reviewed online.', target)
            value.update(id=f'{provider}-{suffix}-{"region" if region else "point"}', createdAt='2026-11-04T13:00:00.000Z',
                         updatedAt='2026-11-04T14:00:00.000Z', state='resolved',
                         severity='major', tags=['power'], mentions=['reviewer'])
            yield value


@pytest.mark.parametrize('value', list(examples()), ids=lambda value: value['id'])
def test_online_marker_changes_update_geometry_and_metadata_only_when_synced(value):
    target = value['anchor']
    decoded = read_markers(markdown(value), target)
    assert decoded == [value]
    rows = [dict(id='remote-12', body=markdown(value), author='reviewer', annotations=decoded)]
    placed, _ = markers_from_rows(rows, target, 'synced')
    assert len(placed) == 1 and placed[0].state == 'resolved'
    assert (placed[0].x, placed[0].y) == (12.5, 8.25)
    assert markers_from_rows(rows, target, 'offline / stale')[0] == []
    assert read_markers(markdown(value), dict(target, ref='b' * 40)) == []


def test_actual_online_parser_roundtrip_when_explicitly_supplied():
    selected = os.environ.get('WAYRICAD_KIVIEW_REVIEW_MODULE')
    if not selected or not shutil.which('node'):
        pytest.skip('Supply WAYRICAD_KIVIEW_REVIEW_MODULE and Node for actual online-parser interoperability.')
    module = Path(selected).resolve(strict=True)
    source = r'''
const fs = require('node:fs');
const review = require(process.argv[1]);
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = cases.map(({body}) => {
  const notes = review.fromMarkdown(body);
  if (notes.length !== 1) throw Error('Desktop marker was rejected by online parser');
  const note = notes[0];
  const exported = review.exportComments(notes);
  const sidecar = review.serializeSidecar(notes);
  if (review.parseComments(exported).length !== 1 || review.parseSidecar(sidecar).length !== 1)
    throw Error('Online JSON formats did not retain the marker');
  return {note, body:review.toMarkdown(note)};
});
process.stdout.write(JSON.stringify(results));
'''
    values = list(examples())
    result = subprocess.run(['node', '-e', source, str(module)],
                            input=json.dumps([dict(body=markdown(value)) for value in values]),
                            capture_output=True, text=True, encoding='utf-8', timeout=15,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    returned = json.loads(result.stdout)
    assert len(returned) == len(values)
    for expected, actual in zip(values, returned):
        assert actual['note']['anchor'] == expected['anchor']
        imported = read_markers(actual['body'], expected['anchor'])
        assert len(imported) == 1
        for field in ('id', 'text', 'anchor', 'state', 'severity', 'tags', 'mentions', 'updatedAt'):
            assert imported[0][field] == expected[field]
