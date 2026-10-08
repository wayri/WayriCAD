from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import math
import re
import copy

MAX_INSTANCES = 100
MAX_COLUMNS = 100

class MergeError(RuntimeError):
    pass


def validate_source_aliases(sources):
    seen=set()
    for source in sources:
        alias=source.alias
        if not isinstance(alias,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,23}',alias):
            raise MergeError('Source aliases must be 1–24 letters/digits/underscores, beginning with a letter.')
        if alias.casefold() in seen:raise MergeError('Source aliases must be unique, ignoring case.')
        seen.add(alias.casefold())

@dataclass
class SourceSpec:
    project: str
    alias: str
    x_mm: float | None = None
    y_mm: float | None = None
    variant: str | None = None
    path_variables: dict[str, str] = field(default_factory=dict)
    path_remaps: dict[str, str] = field(default_factory=dict)
    extra_asset_paths: list[str] = field(default_factory=list)
    # Reviewed, materialized section copies use the ordinary merge pipeline.
    # The exact original sheet occurrence and rectangle survive setup roundtrips.
    section_origin: dict = field(default_factory=dict)
    selection: dict = field(default_factory=dict)
    sheet_position_mm: list[float] = field(default_factory=list)
    variant_mode: str = 'base'
    destination_variant: str = '<Default>'

    @property
    def kind(self):
        return 'section' if self.section_origin else 'project'


def validate_section_origin(source):
    if source.variant_mode not in {'base','merge','separate'}:
        raise MergeError(f'{source.alias}: unknown variant handling mode.')
    if not isinstance(source.destination_variant,str) or not source.destination_variant.strip():
        raise MergeError(f'{source.alias}: choose a destination variant name.')
    if (source.destination_variant!=source.destination_variant.strip() or len(source.destination_variant)>128
            or any(ord(char)<32 for char in source.destination_variant)):
        raise MergeError('Destination variant names need 1–128 visible characters without surrounding whitespace.')
    if source.variant_mode=='separate' and source.destination_variant=='<Default>':
        raise MergeError('A separate variant needs a new named configuration, not <Default>.')
    origin = source.section_origin
    if not isinstance(origin, dict):
        raise MergeError(f'{source.alias}: section_origin must be an object.')
    if not origin:
        return
    if not {'project', 'sheet_path', 'region_mm'} <= set(origin) or set(origin)-{'project','sheet_path','region_mm','max_depth'}:
        raise MergeError(f'{source.alias}: section origin needs project, sheet_path and region_mm.')
    depth=origin.get('max_depth')
    if depth is not None and (isinstance(depth,bool) or not isinstance(depth,int) or not 0<=depth<=31):
        raise MergeError('Section origin depth must be 0–31 or unlimited.')
    if not all(isinstance(origin[key], str) and origin[key].strip() for key in ('project', 'sheet_path')):
        raise MergeError(f'{source.alias}: section origin paths must be nonempty strings.')
    region = origin['region_mm']
    # Schematic-only sections have no physical selection rectangle.
    if region is None:
        return
    if not isinstance(region, (list, tuple)) or len(region) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 10000 for v in region):
        raise MergeError(f'{source.alias}: section region needs four finite millimetre coordinates.')
    if region[0] >= region[2] or region[1] >= region[3]:
        raise MergeError(f'{source.alias}: section region must be a positive rectangle.')


def duplicate_sources(sources, selected_indices, copies):
    """Atomically build independent instances adjacent to their originals."""
    indices = set(selected_indices)
    if not indices or any(isinstance(i, bool) or not isinstance(i, int) or i < 0 or i >= len(sources) for i in indices):
        raise MergeError('Select valid merge instances to duplicate.')
    if isinstance(copies, bool) or not isinstance(copies, int) or copies < 1:
        raise MergeError('Specify a positive number of additional copies per instance.')
    if len(sources) + len(indices) * copies > MAX_INSTANCES:
        raise MergeError(f'A maximum of {MAX_INSTANCES} merge instances is allowed.')
    validate_source_aliases(sources)
    used = {s.alias.casefold() for s in sources}
    result = []
    for index, source in enumerate(sources):
        result.append(copy.deepcopy(source))
        if index not in indices:
            continue
        for _ in range(copies):
            number = 2
            while True:
                suffix = f'_{number}'
                alias = source.alias[:24-len(suffix)] + suffix
                if alias.casefold() not in used:
                    break
                number += 1
            clone = copy.deepcopy(source)
            clone.alias = alias
            clone.x_mm = clone.y_mm = None
            used.add(alias.casefold())
            result.append(clone)
    return result

@dataclass
class Options:
    sources: list[SourceSpec]
    destination: str
    name: str = 'Combined'
    annotation: str = 'sequential'
    block_size: int = 1000
    columns: int = 2
    gap_mm: float = 10.0
    margin_mm: float = 5.0
    outline: str = 'rectangle'
    acknowledge_outline_change: bool = False
    accept_primary_settings: bool = False
    saved_sources_confirmed: bool = False
    cli_path: str = ''
    acknowledge_layer_remap: bool = False
    strict_assets: bool = True
    copy_assets: bool = True

    def validate(self):
        if not 1 <= len(self.sources) <= MAX_INSTANCES:
            raise MergeError(f'Select between 1 and {MAX_INSTANCES} merge instances.')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', self.name):
            raise MergeError('Output name: use a letter followed by letters, digits, underscores or hyphens (maximum 64 characters).')
        aliases = []
        for s in self.sources:
            if s.sheet_position_mm and (len(s.sheet_position_mm)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>10000 for v in s.sheet_position_mm)):
                raise MergeError('Sheet placement requires two finite millimetre coordinates within ±10000 mm.')
            validate_section_origin(s)
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,23}', s.alias):
                raise MergeError(f'Invalid source alias {s.alias!r}. Use 1–24 letters/digits/underscores, beginning with a letter.')
            aliases.append(s.alias.casefold())
            if s.variant is not None and (not isinstance(s.variant,str) or not s.variant.strip()):
                raise MergeError(f'{s.alias}: select a named variant or <Default>.')
            for key in ('path_variables','path_remaps'):
                value = getattr(s,key)
                if not isinstance(value,dict) or not all(isinstance(k,str) and k and isinstance(v,str) and v for k,v in value.items()):
                    raise MergeError(f'{s.alias}: {key} must contain nonempty string keys and values.')
            if 'KIPRJMOD' in s.path_variables:
                raise MergeError('KIPRJMOD is source-specific and cannot be overridden; use path_remaps instead.')
            if not isinstance(s.extra_asset_paths,list) or not all(isinstance(v,str) and v for v in s.extra_asset_paths):
                raise MergeError('extra_asset_paths must be a list of nonempty paths.')
            if (s.x_mm is None) != (s.y_mm is None):
                raise MergeError(f'{s.alias}: specify both X and Y, or neither.')
            if s.x_mm is not None and not all(math.isfinite(v) and abs(v) <= 10000 for v in (s.x_mm,s.y_mm)):
                raise MergeError('Placement coordinates must be finite and within ±10000 mm.')
        if len(set(aliases)) != len(aliases):
            raise MergeError('Source aliases must be unique, ignoring case.')
        if self.annotation not in {'sequential','blocks'}:
            raise MergeError('Unknown annotation policy.')
        if not 10 <= self.block_size <= 1000000:
            raise MergeError('Reference block size must be 10–1000000.')
        if isinstance(self.columns,bool) or not isinstance(self.columns,int) or not 1 <= self.columns <= MAX_COLUMNS:
            raise MergeError(f'Column count must be 1–{MAX_COLUMNS}.')
        if not all(math.isfinite(v) and 0 <= v <= 1000 for v in (self.gap_mm,self.margin_mm)):
            raise MergeError('Gap and margin must be finite and between 0 and 1000 mm.')
        if self.outline not in {'rectangle','preserve'}:
            raise MergeError('Unknown outline policy.')
        if self.outline == 'rectangle' and not self.acknowledge_outline_change:
            raise MergeError('Acknowledge that rectangular-board mode moves ALL source Edge.Cuts, including slots/cutouts, to Dwgs.User. Recreate required internal cutouts before manufacture.')
        if not self.saved_sources_confirmed:
            raise MergeError('Save all source schematic and PCB editors, then confirm saved-file operation.')
        if not self.destination.strip():
            raise MergeError('Choose a new output folder.')

    @classmethod
    def from_json(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        data.pop('_workspace',None)
        data['sources'] = [SourceSpec(**s) for s in data['sources']]
        return cls(**data)

    def to_dict(self):
        return asdict(self)
