"""Portable, source-bound setup files; loading never executes project code."""
import json
import re
from pathlib import Path

from .backend import atomic_json
from .model import source_identity, validate_config


def read_setup(path):
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Setup file exceeds the 8 MiB limit.')
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(record, dict) or set(record) - {'schema','kind','plugin','source','config'} or
            type(record.get('schema')) is not int or
            record['schema'] != 1 or record.get('plugin', 'quick-emerge') != 'quick-emerge' or
            record.get('kind', 'wayricad-setup') != 'wayricad-setup' or 'config' not in record):
        raise ValueError('Choose a Quick EMerge setup file, not a result or another tool’s setup.')
    config = validate_config(record['config'])
    advanced = config['advanced']
    if advanced['step_path']:
        from .advanced import verify_step
        verify_step(advanced)
    if advanced['import_kind'] != 'none':
        from .advanced_imports import import_identity
        current = import_identity(advanced['import_kind'], advanced['import_path'], advanced['import_recipe_path'])
        if current['sha256'] != advanced['import_sha256']:
            raise ValueError('The fabrication source or reviewed recipe changed after this setup was saved.')
    source = record.get('source')
    if source is not None and (not isinstance(source, dict) or not isinstance(source.get('path'), str) or
                              re.fullmatch('[0-9a-f]{64}', str(source.get('sha256', ''))) is None):
        raise ValueError('Malformed setup source identity.')
    return config, source


def write_setup(path, board, config):
    path = Path(path).expanduser()
    if not path.suffix:
        path = path.with_suffix('.json')
    if path.suffix.lower() != '.json':
        raise ValueError('Save setup using a .json filename.')
    config = validate_config(config)
    protected = [board] + [config['advanced'].get(key) for key in
                           ('step_path', 'import_path', 'import_recipe_path')]
    for source in protected:
        if source and Path(source).resolve() == path.resolve():
            raise ValueError('A setup file must not overwrite its board or an imported source.')
    atomic_json(path, {'schema': 1, 'kind': 'wayricad-setup', 'plugin': 'quick-emerge',
                       'source': source_identity(board), 'config': config})
    return path.resolve()


def validate_region_choices(config, listing):
    if not any(area['id'] == config['rule_area_id'] for area in listing['areas']):
        raise ValueError('The setup’s rule area is not present in this saved PCB. Select a current rule area.')
    nets = listing['copper_net_names']
    if any(config[key] not in nets for key in ('signal_net', 'reference_net')):
        raise ValueError('The setup’s signal or reference net is not present in this saved PCB. Select current nets.')
