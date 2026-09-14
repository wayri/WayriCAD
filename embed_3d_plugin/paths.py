"""Resolve local KiCad models without inventing a physical-part substitution.

Native expansions are captured on the GUI thread before scanning. This class
then contains only Python data, so file IO/compression may use a worker thread.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import sys
from .sexpr import parse

VAR = re.compile(r'\$\{([^}]+)\}|\$\(([^)]+)\)|\$([A-Za-z_][A-Za-z_0-9]*)|%([^%]+)%')
STANDARD = ('KICAD10_3DMODEL_DIR', 'KICAD10_FOOTPRINT_DIR', 'KICAD_STOCK_DATA_HOME', 'KISYS3DMOD')

class ResolutionError(ValueError):
    pass


def config_dirs():
    root = os.environ.get('KICAD_CONFIG_HOME')
    if root:
        yield Path(root)/'10.0'
        yield Path(root)
    if os.name == 'nt':
        yield Path(os.environ.get('APPDATA', str(Path.home()/'AppData'/'Roaming')))/'kicad'/'10.0'
    elif sys.platform == 'darwin':
        yield Path.home()/'Library'/'Preferences'/'kicad'/'10.0'
    else:
        yield Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'kicad'/'10.0'


def stock_data_roots():
    roots = [Path('/usr/share/kicad'), Path('/usr/local/share/kicad'), Path('/app/share/kicad'),
             Path('/Applications/KiCad/KiCad.app/Contents/SharedSupport'),
             Path('/Library/Application Support/kicad')]
    if os.environ.get('KICAD_STOCK_DATA_HOME'):
        roots.insert(0, Path(os.environ['KICAD_STOCK_DATA_HOME']))
    for env in ('ProgramW6432', 'ProgramFiles'):
        if os.environ.get(env):
            roots.append(Path(os.environ[env])/'KiCad'/'10.0'/'share'/'kicad')
    module = sys.modules.get('pcbnew')
    origins = [Path(sys.executable)]
    if module and getattr(module, '__file__', None):
        origins.append(Path(module.__file__))
    for origin in origins:
        for parent in origin.resolve().parents:
            roots.extend((parent/'share'/'kicad', parent/'SharedSupport'))
    return list(dict.fromkeys(roots))


def configured_variables(project: Path | None = None):
    values = {}
    for folder in reversed(list(config_dirs())):
        try:
            raw = json.loads((folder/'kicad_common.json').read_text(encoding='utf-8')).get('environment', {}).get('vars', {})
            if isinstance(raw, dict):
                values.update({k: str(v) for k, v in raw.items() if isinstance(v, (str, int, float))})
        except (OSError, ValueError):
            pass
    values.update(os.environ)
    roots = stock_data_roots()
    for name, subdirs in (('KICAD10_3DMODEL_DIR', ('3dmodels', 'packages3d')),
                          ('KICAD10_FOOTPRINT_DIR', ('footprints',))):
        if name not in values:
            for path in (root/sub for root in roots for sub in subdirs):
                if path.is_dir():
                    values[name] = str(path)
                    break
    if project:
        values['KIPRJMOD'] = str(project.resolve())
    return values


class Resolver:
    def __init__(self, project: Path | None = None, variables: dict | None = None):
        self.project = project.resolve() if project else None
        self.variables = configured_variables(self.project)
        self.explicit = {k: str(v) for k, v in (variables or {}).items()}
        self.variables.update(self.explicit)
        self.native_references = {}
        self.native_available = False
        self.native_notes = []

    def capture_native(self, pcbnew, project_object=None, references=()):
        """MUST run on the GUI thread. Freeze KiCad's live defaults/expansion.

        No pcbnew object is retained by the resolver. Explicit session variables
        override live values, including overrides made while repairing a link.
        """
        fn = getattr(pcbnew, 'ExpandEnvVarSubstitutions', None)
        if not callable(fn):
            return
        names = set(STANDARD)
        for ref in references:
            names.update(next(g for g in m.groups() if g is not None) for m in VAR.finditer(ref))
        # Read library URI variables too; unresolved rows must not hide other libraries.
        tables = [d/'fp-lib-table' for d in config_dirs()]
        if self.project:
            tables.append(self.project/'fp-lib-table')
        for table in tables:
            try:
                value = table.read_text(encoding='utf-8')
                names.update(next(g for g in m.groups() if g is not None) for m in VAR.finditer(value))
            except OSError:
                pass
        for name in sorted(names):
            if name in self.explicit or name == 'KIPRJMOD':
                continue
            token = '${'+name+'}'
            try:
                value = str(fn(token, project_object))
                if value and value != token and not VAR.search(value):
                    self.variables[name] = value
                    self.native_available = True
            except Exception as exc:
                self.native_notes.append(name+': '+str(exc))
        for ref in references:
            used = {next(g for g in m.groups() if g is not None) for m in VAR.finditer(ref)}
            # Do not let a native KIPRJMOD expansion defeat the chosen project folder.
            if used.intersection(self.explicit) or 'KIPRJMOD' in used:
                continue
            try:
                value = str(fn(ref, project_object))
                if value and value != ref and not VAR.search(value):
                    self.native_references[ref] = value
            except Exception:
                pass

    def expand(self, value: str) -> str:
        def substitute(match):
            name = next(g for g in match.groups() if g is not None)
            if name in self.variables:
                return self.variables[name]
            old = re.fullmatch(r'KICAD\d+_(3DMODEL_DIR|FOOTPRINT_DIR)', name)
            if old:
                return self.variables.get('KICAD10_'+old.group(1), match.group(0))
            if name == 'KISYS3DMOD':
                return self.variables.get('KICAD10_3DMODEL_DIR', match.group(0))
            return match.group(0)
        for _ in range(16):
            updated = VAR.sub(substitute, value)
            if updated == value:
                break
            value = updated
        if VAR.search(value):
            raise ResolutionError('Undefined or recursive path variable: '+value+
                                  '. Check Path settings or choose the stock 3D models folder.')
        return os.path.expanduser(value)

    def model_roots(self):
        result = []
        # Current default first; explicitly configured old versions are also useful
        # for user-confirmed searches, not automatic same-basename substitution.
        for name in ('KICAD10_3DMODEL_DIR', 'KISYS3DMOD'):
            if self.variables.get(name):
                try:
                    path = Path(self.expand(self.variables[name]).replace('\\', '/'))
                    if path not in result:
                        result.append(path)
                except ResolutionError:
                    pass
        return result

    def resolve(self, reference: str, source_dir: Path | None = None) -> Path:
        if reference.startswith('kicad-embed://'):
            raise ResolutionError('Reference is already embedded')
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', reference):
            raise ResolutionError('Remote URLs are not fetched; locate a local model instead')
        original = reference
        match = re.match(r'^:([^:]+):(.+)$', reference)
        if match:
            name, rest = match.groups()
            if name not in self.variables:
                raise ResolutionError('Unknown 3D alias: '+name)
            reference = self.variables[name].rstrip('/\\')+'/'+rest.lstrip('/\\')
        expanded = self.expand(self.native_references.get(original, reference)).replace('\\', '/')
        if os.name != 'nt' and re.match(r'^[A-Za-z]:/', expanded):
            raise ResolutionError('Windows drive path needs an explicit local replacement')
        p = Path(expanded)
        if p.is_absolute():
            candidates = [p]
        else:
            candidates = []
            if self.project:
                candidates.append(self.project/p)
            if source_dir:
                candidates.append(source_dir/p)
            # KiCad's standard model resolver searches the stock model root for
            # relative "Resistor_SMD.3dshapes/R_....step" links as well.
            candidates.extend(root/p for root in self.model_roots())
            if not candidates:
                raise ResolutionError('Relative model path needs a project, footprint, or stock models directory')
        existing = []
        for candidate in candidates:
            if candidate.is_file():
                real = candidate.resolve()
                if real not in existing:
                    existing.append(real)
        if len(existing) > 1:
            raise ResolutionError('Ambiguous relative model path; use Locate model to choose explicitly: '+
                                  ' | '.join(str(p) for p in existing))
        if not existing:
            raise ResolutionError('File not found. Tried: '+' | '.join(str(p) for p in dict.fromkeys(candidates))+
                                  '. Use Find missing… or Locate model…; missing files are not downloaded.')
        return existing[0]

    def footprint_libraries(self, project_dir: Path | None = None):
        result = {}
        paths = [d/'fp-lib-table' for d in reversed(list(config_dirs()))]
        if project_dir:
            paths.append(project_dir/'fp-lib-table')
        for path in paths:
            try:
                text = path.read_text(encoding='utf-8')
                nodes = parse(text).nodes(text, 'lib')
            except (OSError, ValueError):
                continue
            for node in nodes:
                try:
                    name, uri = node.one(text, 'name'), node.one(text, 'uri')
                    if name and uri:
                        resolved = Path(self.expand(uri.arg().value(text)))
                        if not resolved.is_absolute() and self.project:
                            resolved = self.project/resolved
                        result[name.arg().value(text)] = resolved
                except ValueError:
                    continue
        return result

    def diagnostics(self):
        # Never export the whole environment: it can contain credentials.
        names = set(STANDARD) | {k for k in self.variables if re.fullmatch(r'KICAD\d+_(3DMODEL_DIR|FOOTPRINT_DIR)', k)}
        return {'native_expansion_captured': self.native_available, 'project': str(self.project or ''),
                'stock_variables': {k: self.variables[k] for k in sorted(names) if k in self.variables},
                'model_roots': [str(p) for p in self.model_roots()], 'native_notes': self.native_notes}


def exact_name_candidates(references, roots, cancelled=lambda: False, max_files=150000):
    """One bounded search per selected root. Candidate paths require user approval.

    Match exact basenames only, never R_0402 to R_0603 or STEP to WRL. File names
    are not identity: duplicate candidates stay ambiguous even when sizes match.
    """
    names = {str(ref).replace('\\', '/').rsplit('/', 1)[-1] for ref in references}
    result = {name: [] for name in names}
    count, seen = 0, set()
    for root in roots:
        root = Path(root).resolve()
        if root in seen:
            continue
        seen.add(root)
        def raise_walk_error(error):
            raise error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=raise_walk_error):
            dirs[:] = [d for d in dirs if not d.startswith('.') and not (Path(directory)/d).is_symlink()]
            if cancelled():
                raise InterruptedError('Search cancelled')
            count += len(files)
            if count > max_files:
                raise ValueError('Search exceeds 150,000 files. Choose a narrower 3D-model folder.')
            for name in names.intersection(files):
                path = (Path(directory)/name).resolve()
                if path.is_file() and path not in result[name]:
                    result[name].append(path)
    return {name: sorted(paths) for name, paths in result.items()}
