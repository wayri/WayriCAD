"""Validated, offline vendor discovery and portable custom-profile interchange.

Search is discovery, not process qualification. Imported source dates are user
assertions, not authenticated vendor approval. No function writes bundled data.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from . import checklists as c


CATALOG_SCHEMA = 'wayricad.vendor-catalog/v1'


def _https(value):
    url = urlsplit(c._text(value, 'source URL'))
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Source URL must be an HTTPS reference.')


def validate_catalog(catalog):
    """Validate both directory and profile cross-references; return a copy."""
    c._keys(catalog, ('schema', 'retrieved', 'notes', 'profiles', 'vendors'))
    if catalog['schema'] != CATALOG_SCHEMA:
        raise ValueError('Unsupported vendor-catalog schema.')
    c._day(catalog['retrieved'], 'catalog retrieved')
    c._text(catalog['notes'], 'catalog notes', empty=True)
    for field in ('profiles', 'vendors'):
        if not isinstance(catalog[field], list) or len(catalog[field]) > 1000:
            raise ValueError('Invalid catalog collection: ' + field)
    vendor_ids, vendor_names = set(), set()
    for vendor in catalog['vendors']:
        c._keys(vendor, ('id', 'name', 'region', 'services', 'source_urls', 'status', 'notes'))
        identifier = c._identifier(vendor['id'])
        name = c._text(vendor['name'], 'vendor name').casefold()
        if identifier in vendor_ids or name in vendor_names:
            raise ValueError('Duplicate vendor identifier/name.')
        vendor_ids.add(identifier)
        vendor_names.add(name)
        for field in ('region', 'notes'):
            c._text(vendor[field], field, empty=field == 'notes')
        if vendor['status'] not in ('profiles_available', 'needs_vendor_confirmation'):
            raise ValueError('Unsupported vendor status.')
        for field in ('services', 'source_urls'):
            values = vendor[field]
            if not isinstance(values, list) or not values or len(values) > 256:
                raise ValueError('Invalid vendor ' + field)
            for value in values:
                c._text(value, field)
                if field == 'source_urls':
                    _https(value)
            if len(values) != len(set(values)):
                raise ValueError('Duplicate vendor ' + field)
    identifiers = set()
    for profile in catalog['profiles']:
        c.validate_profile(profile)
        if profile['id'] in identifiers:
            raise ValueError('Duplicate profile identifier.')
        identifiers.add(profile['id'])
        if profile['vendor'].casefold() not in vendor_names:
            raise ValueError('Profile vendor is missing from the directory.')
    return deepcopy(catalog)


def load_catalog(path=None):
    """Load bounded UTF-8 JSON, rejecting duplicate keys and malformed profiles."""
    return c._load(Path(path) if path is not None else Path(__file__).with_name('vendor_catalog.json'),
                   validate_catalog)


def _matches(query, values):
    c._text(query, 'search query', empty=True)
    haystack = ' '.join(values).casefold()
    return all(term in haystack for term in query.casefold().split())


def search_profiles(catalog, query='', *, vendor=None, layers=None, copper_oz=None,
                    board_type=None, copper_basis=None):
    """Find explicitly scoped profiles; unknown scope does not match a filter.

    Copper filters concern outer copper; inner scope remains in the returned
    process. No result establishes compatibility, freshness or quote acceptance.
    """
    catalog = validate_catalog(catalog)
    if layers is not None:
        c._number(layers, 'layer filter', positive=True)
        if int(layers) != layers:
            raise ValueError('Layer filter must be an integer.')
    if copper_oz is not None:
        c._number(copper_oz, 'copper filter', positive=True)
    for value in (vendor, board_type, copper_basis):
        if value is not None:
            c._text(value, 'search filter')
    if copper_basis is not None and copper_basis not in c.COPPER_BASES:
        raise ValueError('Unsupported copper basis.')
    result = []
    for profile in catalog['profiles']:
        process = profile['process']
        if vendor is not None and profile['vendor'].casefold() != vendor.casefold():
            continue
        if layers is not None and layers not in (process['layers'] or []):
            continue
        if copper_oz is not None and copper_oz not in (process['copper_oz'] or []):
            continue
        if board_type is not None and process['board_type'] != board_type:
            continue
        if copper_basis is not None and process.get('copper_basis') != copper_basis:
            continue
        if _matches(query, [profile[key] for key in ('id', 'name', 'vendor', 'service')]
                    + [process.get('material') or '', profile.get('notes', '')]):
            result.append(profile)
    return result


def search_vendors(catalog, query=''):
    """Search directory names, region, service labels and notes, including unprofiled vendors."""
    catalog = validate_catalog(catalog)
    return [vendor for vendor in catalog['vendors']
            if _matches(query, [vendor[key] for key in ('id', 'name', 'region', 'notes')]
                        + vendor['services'])]


def export_profile(profile):
    """Return portable UTF-8 JSON text; callers may use checklists.save_profile."""
    payload = json.dumps(c.validate_profile(profile), ensure_ascii=False,
                         allow_nan=False, indent=2) + '\n'
    if len(payload.encode('utf-8')) > c.MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds the size limit.')
    return payload


def import_custom_profile(catalog, text):
    """Return a new catalog with one validated profile; never replace an ID.

    A newly named supplier gets an explicitly user-supplied directory entry.
    Importing is not source verification; this does not run or pass any check.
    """
    result = validate_catalog(catalog)
    if not isinstance(text, str):
        raise ValueError('Expected UTF-8 JSON text.')
    try:
        size = len(text.encode('utf-8'))
    except UnicodeError as exc:
        raise ValueError('Malformed profile text.') from exc
    if size > c.MAX_DOCUMENT_BYTES:
        raise ValueError('Document exceeds the size limit.')
    try:
        profile = c.validate_profile(json.loads(text.lstrip('\ufeff'), object_pairs_hook=c._reject_duplicates))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Malformed profile JSON.') from exc
    if any(row['id'] == profile['id'] for row in result['profiles']):
        raise ValueError('Profile ID already exists; choose a new custom identifier.')
    vendor = next((row for row in result['vendors']
                   if row['name'].casefold() == profile['vendor'].casefold()), None)
    if vendor is None:
        urls = list(dict.fromkeys(source['url'] for source in profile['sources']))
        if not urls:
            raise ValueError('A new supplier needs at least one source reference.')
        identifier = 'custom-' + hashlib.sha256(profile['vendor'].casefold().encode('utf-8')).hexdigest()[:24]
        result['vendors'].append(dict(id=identifier, name=profile['vendor'], region='User supplied',
                                      services=['User supplied'], source_urls=urls,
                                      status='profiles_available',
                                      notes='Custom imported profile; source claims need independent confirmation.'))
    else:
        profile['vendor'] = vendor['name']
        vendor['status'] = 'profiles_available'
    result['profiles'].append(profile)
    return validate_catalog(result)
