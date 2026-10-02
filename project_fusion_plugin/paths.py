"""Resolve paths on the user's computer. Never fetch network resources.

KiCad variables can live in kicad_common.json rather than os.environ. Explicit
per-source overrides/remaps make projects moved between computers recoverable.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import re
import sys
from urllib.parse import unquote, urlparse
from .model import MergeError

EMBED_SCHEMES = ('kicad-embed://', 'embedded://')
REMOTE = re.compile(r'^(?:https?|ftp|sftp|git|ssh)://', re.I)
VAR = re.compile(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z_0-9]*)|%([^%]+)%')


def config_directories():
    roots = []
    if os.environ.get('KICAD_CONFIG_HOME'):
        p = Path(os.environ['KICAD_CONFIG_HOME']).expanduser()
        roots.extend([p / '10.0', p])
    if os.environ.get('APPDATA'):
        roots.append(Path(os.environ['APPDATA']) / 'kicad' / '10.0')
    roots.append(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config'))) / 'kicad' / '10.0')
    return list(dict.fromkeys(p.resolve() for p in roots))


def variable_context(source):
    cached = getattr(source, '_path_context', None)
    if cached is not None:
        return cached
    values = {}
    for directory in reversed(config_directories()):
        p = directory / 'kicad_common.json'
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding='utf-8-sig'))
                variables = data.get('environment', {}).get('vars', {})
                if isinstance(variables, dict):
                    values.update({k: str(v) for k, v in variables.items() if isinstance(v, (str,int,float))})
            except (OSError, ValueError, AttributeError) as e:
                raise MergeError(f'Cannot read KiCad path configuration {p}: {e}') from e
    values.update(os.environ)
    if 'KICAD10_3RD_PARTY' not in values:
        data_root = (Path.home()/'Documents'/'KiCad'/'10.0' if os.name=='nt' else
                     Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local'/'share')))/'kicad'/'10.0')
        third_party = data_root/'3rdparty'
        if third_party.is_dir():
            values['KICAD10_3RD_PARTY'] = str(third_party)
    # KiCad's compiled defaults need not appear in its JSON or process environment.
    roots = [Path('/usr/share/kicad'), Path('/usr/local/share/kicad')]
    for base in filter(None, [os.environ.get('ProgramFiles'), os.environ.get('ProgramW6432')]):
        roots.append(Path(base)/'KiCad'/'10.0'/'share'/'kicad')
    for p in list(Path(sys.executable).parents)[:4]:
        roots.extend([p/'share'/'kicad', p/'kicad'/'share'/'kicad'])
    try:
        import pcbnew
        for p in list(Path(pcbnew.__file__).parents)[:5]:
            roots.append(p/'share'/'kicad')
    except ImportError:
        pass
    for key, suffix in [('KICAD10_FOOTPRINT_DIR','footprints'), ('KICAD10_SYMBOL_DIR','symbols'), ('KICAD10_3DMODEL_DIR','3dmodels')]:
        if key not in values:
            hit = next((p/suffix for p in roots if (p/suffix).is_dir()), None)
            if hit:
                values[key] = str(hit)
    values.update({k: str(v) for k, v in source.project.get('text_variables', {}).items()})
    values.update(source.spec.path_variables)
    values['KIPRJMOD'] = str(source.project_file.parent)
    if getattr(source, 'selected_variant', None) not in (None, '<Default>'):
        values['VARIANT'] = source.selected_variant
    source._path_context = values
    return values


def expand_variables(text, source):
    values = variable_context(source)
    result = str(text)
    seen = set()
    for _ in range(32):
        if result in seen:
            break
        seen.add(result)
        changed = VAR.sub(lambda m: str(values.get(next(g for g in m.groups() if g is not None), m[0])), result)
        if changed == result:
            break
        result = changed
    return result


def resolve_asset(text, source, relative):
    raw = str(text).strip()
    if not raw or raw.startswith(EMBED_SCHEMES) or REMOTE.match(raw):
        return None
    result = expand_variables(raw, source)
    if VAR.search(result):
        return None
    # KiCad 3D model search-path alias syntax, e.g. :MY_MODELS:body.step.
    alias = re.match(r'^:([^:]+):(.+)$', result)
    if alias:
        values = variable_context(source)
        if alias[1] not in values:
            return None
        result = str(values[alias[1]]).rstrip('/\\') + '/' + alias[2]
    if result.lower().startswith('file://'):
        parsed = urlparse(result)
        result = ('//' + parsed.netloc if parsed.netloc else '') + unquote(parsed.path)
        if os.name == 'nt' and re.match(r'^/[A-Za-z]:/', result):
            result = result[1:]
    result = result.replace('\\','/')
    # Longest root prefix wins, on a path-component boundary. No regex/eval.
    for old, new in sorted(source.spec.path_remaps.items(), key=lambda x: len(x[0]), reverse=True):
        old = old.replace('\\','/').rstrip('/')
        if result.casefold() == old.casefold() or result.casefold().startswith(old.casefold()+'/'):
            result = str(new).replace('\\','/').rstrip('/') + result[len(old):]
            break
    if re.match(r'^[A-Za-z]:/', result) and os.name != 'nt':
        return None  # Never interpret a Windows drive as a Linux relative path.
    if '://' in result:
        return None
    p = Path(result).expanduser()
    try:
        return (p if p.is_absolute() else Path(relative)/p).resolve()
    except (OSError, ValueError):
        return None
