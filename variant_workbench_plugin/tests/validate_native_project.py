"""Opt-in, bounded KiCad acceptance on a disposable project copy.

Run: python variant_workbench_plugin/tests/validate_native_project.py SOURCE OUTPUT
SOURCE is a root schematic; OUTPUT must not exist. No source files are edited.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from variant_workbench_plugin import kicad_variant_manager as v


def hashes(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def connectivity(path):
    root = ET.parse(path).getroot()
    return sorted((net.attrib['name'], sorted(tuple(sorted(node.attrib.items()))
                   for node in net.findall('node'))) for net in root.findall('./nets/net'))


def validate(source, output, cli):
    started = time.monotonic()
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists() or output == source.parent or source.parent in output.parents:
        raise ValueError('Output must be a new directory outside the source project.')
    original = hashes(source.parent)
    output.mkdir(parents=True)
    project = output / 'project'
    shutil.copytree(source.parent, project)
    root = project / source.name
    config = output / 'config'; config.mkdir()
    env = dict(os.environ, KICAD_CONFIG_HOME=str(config),
               KICAD_DOCUMENTS_HOME=str(config / 'documents'))
    commands = []

    def native(label, variant=None):
        target = output / (label + '.xml')
        cmd = [str(cli), 'sch', 'export', 'netlist', '--format', 'kicadxml',
               '--output', str(target)]
        if variant:
            cmd += ['--variant', variant]
        cmd += [str(root)]
        result = subprocess.run(cmd, cwd=output, env=env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=120,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (output / (label + '.stdout.log')).write_text(result.stdout, encoding='utf-8')
        (output / (label + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
        commands.append({'command': cmd, 'returncode': result.returncode})
        if result.returncode != 0 or not target.exists():
            raise RuntimeError(f'Native {label} failed: {result.stderr[-1500:]}')
        return target

    before = native('before')
    baseline = hashes(project)
    variant = 'WayriCAD_Operation_Validation'
    duplicate = v.plan_duplicate_variant(root, v.DEFAULT_VARIANT, variant)
    assert hashes(project) == baseline, 'Duplicate preview changed files'
    duplicate_backups = v.apply_plan(duplicate)
    rows, _ = v.collect_matrix_rows(root)
    target = next(row for row in rows if row.kind == 'symbol'
                  and row.reference.startswith('R') and not row.base.dnp
                  and row.base.fields.get('Value'))
    patch = v.VariantPatch(file=str(project / target.file), uuid=target.uuid,
                           instance_path=target.instance_path, variant=variant,
                           dnp=True, field_updates={'Value': 'WayriCAD validation 12.3k'})
    baseline = hashes(project)
    plan = v.plan_patch_variants(root, [patch])
    assert hashes(project) == baseline, 'Edit preview changed files'
    (output / 'plan.json').write_text(json.dumps(asdict(plan), indent=2, default=str), encoding='utf-8')
    backups = v.apply_plan(plan)
    after_rows, _ = v.collect_matrix_rows(root)
    changed = next(row for row in after_rows if row.key == target.key)
    originals = {row.key: row for row in rows}
    assert set(originals) == {row.key for row in after_rows}
    for row in after_rows:
        old = originals[row.key]
        assert row.base.signature() == old.base.signature(), row.reference
        for name in old.states:
            if row.key != target.key or name != variant:
                assert row.states[name].signature() == old.states[name].signature(), (row.reference, name)
    assert changed.base.signature() == target.base.signature()
    assert changed.states[variant].dnp
    assert changed.states[variant].fields['Value'] == patch.field_updates['Value']
    after = native('after-default')
    named = native('after-variant', variant)
    expected = connectivity(before)
    assert connectivity(after) == expected, 'Default connectivity changed'
    assert connectivity(named) == expected, 'Named variant connectivity changed'
    comp = ET.parse(named).getroot().find(f'./components/comp[@ref="{target.reference}"]')
    assert comp is not None
    # KiCad's XML is a lossless netlist: base properties stay at component
    # level while named assembly overrides are nested under variants.
    assert comp.findtext('value') == target.base.fields['Value']
    override = comp.find(f'./variants/variant[@name="{variant}"]')
    assert override is not None
    assert override.findtext("./fields/field[@name='Value']") == patch.field_updates['Value']
    assert override.find("property[@name='dnp']").attrib['value'] == '1'
    assert hashes(source.parent) == original, 'Source project changed'
    result = {'execution': 'PASS', 'elapsed_seconds': round(time.monotonic()-started, 2),
              'source_unchanged': True, 'preview_nonmutating': True, 'native_reload': True,
              'connectivity_preserved': True, 'nets': len(expected),
              'reference': target.reference, 'variant': variant,
              'value_before': target.base.fields['Value'], 'value_after': patch.field_updates['Value'],
              'dnp_before': target.base.dnp, 'dnp_after': True,
              'backups': list(map(str, [*duplicate_backups, *backups])),
              'copied_board_unchanged': hashes(project).get(source.with_suffix('.kicad_pcb').name)
                  == original.get(source.with_suffix('.kicad_pcb').name),
              'commands': commands, 'output': str(root)}
    (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--cli', type=Path, default=Path('C:/Program Files/KiCad/10.0/bin/kicad-cli.exe'))
    args = parser.parse_args()
    print(json.dumps(validate(args.source, args.output, args.cli), indent=2))
