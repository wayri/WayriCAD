"""KiCad 10 bridge. Every function in this module runs on KiCad's GUI thread.

Native Parse/Format validate embedded payloads. Live updates use SwapItemData,
not base-class CopyFrom, so UUIDs and the footprint's board identity survive.
The action-plugin wrapper owns the undo snapshot and refresh/connectivity pass.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from .codec import Codec, sha256
from .core import Plan, PREFIX, embedded_entries, verify_sources
from .paths import Resolver
from .sexpr import parse, semantic
from .storage import job_directory, atomic_write, write_json


_BOARD_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\|[^|]*\||[;#][^\n]*|[()]|[^\s\ufeff()"|]+', re.S)


def _board_sections(text, with_spans=False):
    """Read relevant top-level spans without constructing a whole-board AST.

    Filled zones may contain millions of coordinates. KiCad validates those;
    the asset bridge only needs footprints and the board's embedded file pool.
    The lexer still checks root identity, balanced parentheses and string/blob
    termination, so parentheses inside paths or payloads cannot split a span.
    """
    depth = 0
    root_seen = False
    root_head = False
    child_start = None
    child_head = None
    sections = []
    previous = 0
    for match in _BOARD_TOKEN.finditer(text):
        if text[previous:match.start()].strip('\ufeff \t\r\n'):
            raise ValueError('Malformed saved PCB token')
        previous = match.end()
        token = match.group()
        if token.startswith(('#', ';')):
            continue
        if token == '(':
            if depth == 0:
                if root_seen:
                    raise ValueError('Expected one saved PCB root')
                root_seen = True
            elif depth == 1:
                if not root_head:
                    raise ValueError('Choose a saved PCB')
                child_start, child_head = match.start(), None
            depth += 1
        elif token == ')':
            if depth <= 0:
                raise ValueError('Unbalanced saved PCB')
            if depth == 2 and child_head in ('footprint', 'module', 'embedded_files'):
                sections.append((child_head, child_start, match.end()) if with_spans else
                                (child_head, text[child_start:match.end()]))
            depth -= 1
        else:
            if depth == 0:
                raise ValueError('Unexpected data outside saved PCB')
            if depth == 1 and not root_head:
                if token != 'kicad_pcb':
                    raise ValueError('Choose a saved PCB')
                root_head = True
            elif depth == 2 and child_head is None:
                child_head = token
    if depth or not root_head or text[previous:].strip('\ufeff \t\r\n'):
        raise ValueError('Unbalanced or truncated saved PCB')
    return sections


def board_asset_root(text):
    """Sparse span-preserving tree for asset operations; excludes zone geometry."""
    from .sexpr import Atom, Node
    def shifted(node, offset):
        if isinstance(node, Atom):
            return Atom(node.start+offset, node.end+offset, node.kind)
        return Node(node.start+offset, node.end+offset,
                    [shifted(child, offset) for child in node.children])
    children = []
    for name, start, end in _board_sections(text, with_spans=True):
        children.append(shifted(parse(text[start:end]), start))
    return Node(0, len(text), children)


def _asset_snapshot(text):
    sections = _board_sections(text)
    pool = '(kicad_pcb\n' + '\n'.join(raw for name, raw in sections if name == 'embedded_files') + '\n)'
    footprints = [raw for name, raw in sections if name in ('footprint', 'module')]
    return pool, footprints


class NativeBridge:
    def __init__(self, pcbnew):
        self.pcbnew = pcbnew
        self.version = str(pcbnew.Version()) if hasattr(pcbnew, 'Version') else str(pcbnew.GetBuildVersion())
        if not re.search(r'(^|[^\d])10\.\d', self.version):
            raise RuntimeError('WayriCAD Embed3D legacy board adapter requires KiCad 10.x; use the IPC adapter on KiCad 11. Detected '+self.version)
        for method in ('PCB_IO_KICAD_SEXPR', 'GetBoard'):
            if not hasattr(pcbnew, method):
                raise RuntimeError('This KiCad build lacks the required Python API: '+method)
        self.board = pcbnew.GetBoard()
        self.leases = []  # Keep swapped-out children alive until native refresh completes.
        self._detached = []

    def serialize(self, footprint):
        io = self.pcbnew.PCB_IO_KICAD_SEXPR(0)  # 0 includes footprint-owned payload bytes.
        io.Format(footprint)
        text = io.GetStringOutput(True)
        return text.decode('utf-8') if isinstance(text, bytes) else str(text)

    def deserialize(self, text):
        io = self.pcbnew.PCB_IO_KICAD_SEXPR(0)
        raw = io.Parse(text)
        if raw is None:
            raise ValueError('KiCad rejected the footprint')
        fp = raw.Cast()
        if not isinstance(fp, self.pcbnew.FOOTPRINT):
            raise ValueError('KiCad did not return a footprint')
        # KiCad 10's generated SWIG destructor corrupts type registration when
        # ownership is forced onto parsed FOOTPRINT proxies. Keep these borrowed
        # and release detached objects through the native DeleteStructure API.
        raw.thisown = False
        fp.thisown = False
        self._detached.append(fp)
        return fp

    def release_detached(self):
        """Release detached native objects; transferred footprints stay with their board."""
        pending, self._detached = self._detached, []
        for fp in pending:
            if fp.GetParent() is None:
                fp.DeleteStructure()

    def _release_scratch(self, item):
        if item.GetParent() is not None:
            raise ValueError('Refusing to release a board-owned native object')
        self._detached = [fp for fp in self._detached if fp is not item]
        item.DeleteStructure()

    def _save_footprint(self, writer, directory, footprint, board_context=None):
        """Give KiCad's back-side flip a detached board/layer context."""
        previous = footprint.GetParent()
        scratch = self.pcbnew.BOARD()
        context = board_context if board_context is not None else self.board
        if context is not None:
            scratch.SetCopperLayerCount(context.GetCopperLayerCount())
        footprint.SetParent(scratch)
        try:
            writer.FootprintSave(str(directory), footprint)
        finally:
            footprint.SetParent(previous)

    def __del__(self):
        # The bridge owns a reference to its board until this method finishes.
        # Thus parsed footprints transferred to that board are still valid here.
        try:
            self.release_detached()
        except Exception:
            pass

    @staticmethod
    def uid(item):
        return str(item.m_Uuid.AsString())

    @staticmethod
    def children(fp):
        found = {}
        for accessor in ('Pads', 'GraphicalItems', 'Zones', 'Groups', 'GetFields'):
            fn = getattr(fp, accessor, None)
            if fn:
                for child in fn():
                    found[str(child.m_Uuid.AsString())] = child
        return found

    def footprints(self, selected=False):
        if not self.board:
            return []
        result = []
        for fp in self.board.GetFootprints():
            if not selected or fp.IsSelected() or fp.HasSelectedAncestorGroup():
                result.append(fp)
        return sorted(result, key=lambda x: (str(x.GetReference()), self.uid(x)))

    def project_path(self):
        name = str(self.board.GetFileName()) if self.board else ''
        return Path(name).resolve().parent if name else Path.home()

    def snapshot_board(self, path: Path):
        if not self.board:
            raise ValueError('No PCB is open')
        name = str(self.board.GetFileName())
        self.pcbnew.PCB_IO_KICAD_SEXPR().SaveBoard(str(path), self.board)
        if not path.is_file() or not path.stat().st_size:
            raise OSError('Board backup was not written')
        if str(self.board.GetFileName()) != name:
            self.board.SetFileName(name)
            raise RuntimeError('Unexpected filename mutation while making a snapshot')

    def sources(self, selected: bool, resolver: Resolver):
        """Return immutable source text, plus the board's shared embedded pool."""
        fps = self.footprints(selected)
        if not fps:
            raise ValueError('No selected footprints. Select complete footprints, or choose All board footprints.')
        self.prepare_resolver(resolver)
        libraries = resolver.footprint_libraries(resolver.project)
        sources, needs_pool = [], False
        for fp in fps:
            text = self.serialize(fp)
            local = embedded_entries(text)
            for node in parse(text).nodes(text, 'model'):
                ref = node.arg().value(text)
                if ref.startswith(PREFIX):
                    entry = local.get(ref[len(PREFIX):])
                    needs_pool |= not bool(entry and entry.encoded)
            lib_id = str(fp.GetFPIDAsString())
            lib = lib_id.split(':', 1)[0] if ':' in lib_id else ''
            label = '%s  ·  %s' % (fp.GetReference(), fp.GetValue())
            sources.append({'key': self.uid(fp), 'text': text, 'name': label,
                            'source_dir': libraries.get(lib), 'owner': fp, 'source_path': None})
        self.prepare_resolver(resolver, [n.arg().value(s['text']) for s in sources
                                        for n in parse(s['text']).nodes(s['text'], 'model')])
        pool = {}
        if needs_pool:
            with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-scan-') as tmp:
                path = Path(tmp)/'snapshot.kicad_pcb'
                self.snapshot_board(path)
                pool = embedded_entries(path.read_text(encoding='utf-8'))
        return sources, pool

    @staticmethod
    def model_structure(text):
        return [semantic(node.raw(text)) for node in parse(text).nodes(text, 'model')]

    def check_payloads(self, text, actual):
        expected, received = embedded_entries(text), embedded_entries(actual)
        codec = Codec()
        for name, entry in expected.items():
            if not entry.encoded:
                continue
            got = received.get(name)
            if not got or not got.encoded:
                raise ValueError('KiCad did not retain embedded payload: '+name)
            # Native checksum may migrate from SHA256 to MMH3; payload must survive.
            if got.encoded != entry.encoded:
                if codec.decode(got.encoded) != codec.decode(entry.encoded):
                    raise ValueError('KiCad changed embedded model bytes: '+name)

    def validate_file(self, plan, text):
        native_before = self.deserialize(plan.original)
        native_after = self.deserialize(text)
        before, after = self.serialize(native_before), self.serialize(native_after)
        def settings(value):
            return [semantic(n.raw(value), True) for n in parse(value).nodes(value, 'model')]
        refs = lambda value: [n.arg().value(value) for n in parse(value).nodes(value, 'model')]
        if settings(before) != settings(after) or refs(after) != refs(text):
            raise ValueError('KiCad changed a model setting unexpectedly; file was not changed')
        self.check_payloads(text, after)
        self._release_scratch(native_before)
        # Full span-level preservation is separately enforced by Plan.build().
        return native_after

    def prepare_live(self, plan: Plan):
        old = plan.owner
        if old is None or not hasattr(old, 'SwapItemData'):
            raise ValueError('Live embedding requires FOOTPRINT.SwapItemData in this KiCad build. Use library-file mode instead.')
        if self.serialize(old) != plan.original:
            raise ValueError('The PCB changed since preview. Scan again before embedding.')
        old_children = self.children(old)
        # Board groups may contain a pad/graphic directly; do not leave a group
        # pointing to a swapped-out child. Ordinary groups of whole FPs are safe.
        child_ids = set(old_children)
        for group in self.board.Groups():
            if any(self.uid(item) in child_ids for item in group.GetItems()):
                raise ValueError('A board group contains a child of '+plan.name+'. Ungroup that child or export a portable library instead.')
        text = plan.build()
        candidate = self.deserialize(text)
        candidate.SetParent(self.board)
        new_children = self.children(candidate)
        if set(old_children) != set(new_children):
            raise ValueError('Native parser changed child UUIDs in '+plan.name+'; no changes were applied')
        for uid, old_child in old_children.items():
            new_child = new_children[uid]
            if hasattr(old_child, 'GetNet') and hasattr(new_child, 'SetNet'):
                new_child.SetNet(old_child.GetNet())
            # Native selection can retain pointers to old child objects until the
            # action wrapper refreshes. Keep them alive, then clear their selection.
            new_child.ClearSelected()
        candidate.ClearFlags()
        candidate.SetFlags(old.GetFlags())
        actual = self.serialize(candidate)
        if semantic(actual, True) != semantic(plan.original, True):
            raise ValueError('KiCad changed an unrelated footprint setting during preflight for '+plan.name+
                             '. Live update was blocked. Try library-file mode; see the log for diagnostics.')
        if self.model_structure(actual) != self.model_structure(text):
            raise ValueError('Native model transform/reference verification failed for '+plan.name)
        self.check_payloads(text, actual)
        return old, candidate, actual

    def apply_live(self, plans: list[Plan], backup_parent: Path) -> Path:
        chosen = [p for p in plans if p.actionable]
        if not chosen:
            raise ValueError('No models are ready')
        verify_sources(chosen)
        prepared = [self.prepare_live(p) for p in chosen]
        job = job_directory(backup_parent)
        self.snapshot_board(job/'before.kicad_pcb')
        journal = {'format': 'embed_3d_plugin-board-v1', 'status': 'prepared',
                   'original_board': str(self.board.GetFileName()), 'kicad_version': self.version,
                   'plans': [p.manifest() for p in chosen]}
        write_json(job/'manifest.json', journal)
        verify_sources(chosen)
        for p in chosen:
            if self.serialize(p.owner) != p.original:
                raise ValueError('Board changed before apply; scan again')
        swapped = []
        try:
            for old, candidate, expected in prepared:
                group = old.GetParentGroup()
                old.SwapItemData(candidate)
                swapped.append((old, candidate, group))
                self.leases.append(candidate)
                old.SetParent(self.board)
                old.SetParentGroup(group)
                # The old children now belong to candidate. They may still be in
                # KiCad's selection set; let its refresh remove them safely.
                for child in self.children(candidate).values():
                    child.ClearSelected()
                actual = self.serialize(old)
                if semantic(actual, True) != semantic(expected, True):
                    raise RuntimeError('Post-apply footprint verification failed')
                if self.model_structure(actual) != self.model_structure(expected):
                    raise RuntimeError('Post-apply model setting/reference verification failed')
                self.check_payloads(expected, actual)
            journal['status'] = 'applied-in-memory-not-saved'
            write_json(job/'manifest.json', journal)
        except Exception as exc:
            errors = []
            for old, candidate, group in reversed(swapped):
                try:
                    old.SwapItemData(candidate)
                    old.SetParent(self.board)
                    old.SetParentGroup(group)
                except Exception as rollback_error:
                    errors.append(str(rollback_error))
            journal['status'] = 'rollback-needed' if errors else 'rolled-back'
            journal['error'], journal['rollback_errors'] = str(exc), errors
            try:
                write_json(job/'manifest.json', journal)
            except OSError:
                pass
            raise RuntimeError('%s\nRecovery board: %s%s' % (exc, job/'before.kicad_pcb',
                               '\n'+'\n'.join(errors) if errors else '')) from exc
        return job

    def export_library(self, plans: list[Plan], destination: Path) -> Path:
        """Export one footprint per board instance. Never overwrite an existing library."""
        if destination.exists():
            raise ValueError('Choose a NEW .pretty folder; existing libraries are never overwritten by export')
        if destination.suffix.lower() != '.pretty':
            raise ValueError('The destination must end in .pretty')
        chosen = [p for p in plans if p.rows]
        if not chosen:
            raise ValueError('No footprints with models were found')
        for plan in chosen:
            for row in plan.rows:
                if row.status != 'Embedded' and not (row.checked and row.ready):
                    raise ValueError('Portable export requires every model to be embedded. Resolve or check '+plan.name+' / '+row.reference)
        verify_sources(chosen)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.embed_3d_plugin-export-', suffix='.pretty', dir=destination.parent))
        mapping = []
        try:
            writer = self.pcbnew.PCB_IO_KICAD_SEXPR()
            for index, plan in enumerate(chosen):
                text = plan.build()
                fp = self.deserialize(text)
                stem = re.sub(r'[^A-Za-z0-9._-]+', '_', plan.name)[:90].strip('._') or 'footprint'
                name = '%03d_%s' % (index+1, stem)
                libid = fp.GetFPID()
                libid.SetLibNickname(self.pcbnew.UTF8(''))
                libid.SetLibItemName(self.pcbnew.UTF8(name))
                fp.SetFPID(libid)
                self._save_footprint(writer, staging, fp)
                output = staging/(name+'.kicad_mod')
                actual = output.read_text(encoding='utf-8')
                if self.model_structure(actual) != self.model_structure(text):
                    raise ValueError('Library normalization changed model settings for '+plan.name+'; export was cancelled')
                self.check_payloads(text, actual)
                entries = embedded_entries(actual)
                for node in parse(actual).nodes(actual, 'model'):
                    ref = node.arg().value(actual)
                    payload = entries.get(ref[len(PREFIX):]) if ref.startswith(PREFIX) else None
                    if not payload or not payload.encoded:
                        raise ValueError('Export is not self-contained: '+plan.name)
                mapping.append({'file': output.name, 'source': plan.manifest()})
                self._release_scratch(fp)
            writer = None  # Release native library cache before renaming on Windows.
            write_json(staging/'embed_3d_plugin-export.json', {'format': 'embed_3d_plugin-export-v1', 'footprints': mapping})
            if destination.exists():
                raise ValueError('Export destination was created by another process')
            os.rename(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return destination


    def prepare_resolver(self, resolver, references=()):
        """Capture live KiCad path expansion before a worker is started."""
        project = None
        if self.board and hasattr(self.board, 'GetProject'):
            try:
                project = self.board.GetProject()
            except Exception:
                pass
        resolver.capture_native(self.pcbnew, project, references)
        return resolver

    def board_text(self):
        with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-board-') as tmp:
            path = Path(tmp)/'snapshot.kicad_pcb'
            self.snapshot_board(path)
            return path.read_text(encoding='utf-8')

    def normalize_definitions(self, records):
        """Library coordinate/side conversion belongs to KiCad, not custom math.

        Records hold key, name, plan, source_id and origin. Pads/nets on the
        active board are not touched. Includes footprints with no 3D model.
        """
        from .board_package import Definition, safe_name, model_settings
        verify_sources([record['plan'] for record in records])
        definitions = []
        with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-normalize-') as tmp:
            library = Path(tmp)/'normalized.pretty'
            library.mkdir()
            writer = self.pcbnew.PCB_IO_KICAD_SEXPR()
            try:
                for record in records:
                    plan = record['plan']
                    for row in plan.rows:
                        if row.status != 'Embedded' and not (row.ready and row.checked):
                            raise ValueError('Resolve all models before packaging: '+plan.name+' / '+row.reference)
                    if plan.owner is not None and self.serialize(plan.owner) != plan.original:
                        raise ValueError('Board changed since package preview: '+plan.name)
                    text = plan.build()
                    name = safe_name(record['name'])
                    fp = self.deserialize(text)
                    libid = fp.GetFPID()
                    utf8 = getattr(self.pcbnew, 'UTF8', str)
                    libid.SetLibNickname(utf8(''))
                    libid.SetLibItemName(utf8(name))
                    fp.SetFPID(libid)
                    self._save_footprint(writer, library, fp)
                    actual = (library/(name+'.kicad_mod')).read_text(encoding='utf-8')
                    if self.model_structure(text) != self.model_structure(actual):
                        raise ValueError('Native library normalization changed a model transform/reference: '+plan.name)
                    self.check_payloads(text, actual)
                    checked = self.validate_file(plan, actual)
                    self._release_scratch(checked)
                    definitions.append(Definition(record['key'], name, actual,
                                                  record['source_id'], record['origin']))
                    self._release_scratch(fp)
                    fp = None
            finally:
                writer = None
        return definitions

    def validate_package(self, board_path, library):
        """Load/save detached PCB and footprints; do not replace the open board.

        Stops the output if KiCad drops an archived payload, model setting or
        relinked footprint ID. Actual 3D rendering is a separate acceptance test.
        """
        from .board_package import uuid_of, model_settings, model_refs, recover
        expected = Path(board_path).read_text(encoding='utf-8')
        io = self.pcbnew.PCB_IO_KICAD_SEXPR()
        raw = io.Parse(expected)
        if raw is None:
            raise ValueError('KiCad rejected the packaged PCB')
        board = raw.Cast()
        if not isinstance(board, self.pcbnew.BOARD):
            raise ValueError('Native parser did not return a BOARD')
        raw.thisown = False
        board.thisown = False
        self._detached.append(board)
        with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-native-check-') as tmp:
            check = Path(tmp)/'roundtrip.kicad_pcb'
            io.SaveBoard(str(check), board)
            actual = check.read_text(encoding='utf-8')
        self.check_payloads(expected, actual)
        a = {uuid_of(expected, fp): fp.raw(expected) for fp in parse(expected).nodes(expected, 'footprint')}
        b = {uuid_of(actual, fp): fp.raw(actual) for fp in parse(actual).nodes(actual, 'footprint')}
        if set(a) != set(b):
            raise ValueError('Native PCB parse/save changed footprint UUIDs')
        for uid in a:
            if parse(a[uid]).arg().value(a[uid]) != parse(b[uid]).arg().value(b[uid]):
                raise ValueError('KiCad did not preserve a relinked footprint ID')
            if model_settings(a[uid]) != model_settings(b[uid]) or model_refs(a[uid]) != model_refs(b[uid]):
                raise ValueError('KiCad did not preserve a board model setting/reference')
        # Check reconstruction from KiCad's normalized output as well as our text.
        if recover(expected).library_files.keys() != recover(actual).library_files.keys():
            raise ValueError('Native save changed the footprint archive')
        for path in Path(library).glob('*.kicad_mod'):
            text = path.read_text(encoding='utf-8')
            native = self.deserialize(text)
            normalized = self.serialize(native)
            if self.model_structure(text) != self.model_structure(normalized):
                raise ValueError('KiCad changed model settings in reconstructed '+path.name)
            self.check_payloads(text, normalized)
            self._release_scratch(native)
        self._release_scratch(board)
        board = None
        io = None

    def extract_normalized_footprints(self, source_path, cancelled=None, selected_uuids=None):
        """Normalize a SAVED board's instances, never the live editor objects.

        Library coordinate/side handling belongs to KiCad. External unresolved
        model links are retained here; collection is a separate worker operation.
        """
        from .board_package import (slug, safe_name, model_settings, model_refs,
                                    replace_entries, uuid_of)
        from .portability_io import read_bytes
        data = read_bytes(Path(source_path)); text = data.decode('utf-8')
        pool_text, fragments = _asset_snapshot(text)
        pool, result = embedded_entries(pool_text), {}
        # Load legacy footprints in their complete board/version/net context.
        # Parsing an old placed-footprint fragment with KiCad 10's standalone
        # parser can abort the process rather than raise a Python exception.
        saved = self.pcbnew.LoadBoard(str(source_path))
        if saved is None: raise ValueError('KiCad could not load the saved PCB.')
        native_items = {item.m_Uuid.AsString(): item for item in saved.GetFootprints()}
        with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-unbundle-') as tmp:
            library = Path(tmp)/'native.pretty'; library.mkdir()
            for index, raw in enumerate(fragments):
                if cancelled and cancelled(): raise InterruptedError('Footprint normalization cancelled')
                node = parse(raw)
                uid = uuid_of(raw,node)
                if selected_uuids is not None and uid not in selected_uuids: continue
                local = embedded_entries(raw, node)
                original_models = node.nodes(raw, 'model')
                original_refs = [model.arg().value(raw) for model in original_models]
                original_settings = [semantic(model.raw(raw), True) for model in original_models]
                for reference in original_refs:
                    if reference.startswith(PREFIX):
                        key = reference[len(PREFIX):]; entry=local.get(key)
                        if not entry or not entry.encoded: entry=pool.get(key)
                        if not entry: raise ValueError('Missing embedded model data: '+key)
                        local[key]=entry
                if uid not in native_items:raise ValueError('Native board load changed footprint identity: '+uid)
                fp = native_items[uid].Duplicate(False).Cast()
                fp.SetParent(None); fp.thisown=False; self._detached.append(fp)
                original_name = node.arg().value(raw).rsplit(':',1)[-1]
                original_name = re.sub(r'^(?:F\d{5}_)+', '', original_name)
                name=safe_name('F%05d_'%(index+1)+slug(original_name,55))
                libid=fp.GetFPID(); libid.SetLibNickname(self.pcbnew.UTF8('')); libid.SetLibItemName(self.pcbnew.UTF8(name)); fp.SetFPID(libid)
                # FootprintSave maintains a library cache. Retaining every
                # previous file makes each save revisit an ever-growing
                # library; an empty scratch library keeps this operation linear.
                io = self.pcbnew.PCB_IO_KICAD_SEXPR()
                self._save_footprint(io,library,fp,board_context=saved)
                normalized_path = library/(name+'.kicad_mod')
                normalized=normalized_path.read_text(encoding='utf-8')
                io = None
                normalized_path.unlink()
                normalized_node = parse(normalized)
                actual_models = normalized_node.nodes(normalized, 'model')
                actual_refs = [model.arg().value(normalized) for model in actual_models]
                actual_settings = [semantic(model.raw(normalized), True) for model in actual_models]
                if original_settings != actual_settings or original_refs != actual_refs:
                    raise ValueError('Native normalization changed model placement: '+name)
                expected_payloads = '(footprint "payloads" (embedded_files\n' + '\n'.join(e.raw for e in local.values()) + '\n))'
                actual_payloads = normalized_node.one(normalized, 'embedded_files')
                self.check_payloads(expected_payloads, '(footprint "payloads"\n' +
                                    (actual_payloads.raw(normalized) if actual_payloads else '') + '\n)')
                result[uid]=(name,normalized)
                self._release_scratch(fp)
                fp=None
            io=None
        expected_ids = set(native_items) if selected_uuids is None else set(selected_uuids)
        if set(result) != expected_ids:
            raise ValueError('Requested footprint identities were not all preserved during native normalization.')
        if read_bytes(Path(source_path)) != data:
            raise ValueError('Saved PCB changed during native normalization. Preview again.')
        return result,sha256(data)

    def validate_portable_board(self, source):
        """Detached load/save check for relinked PCBs (no archive requirement)."""
        from .board_package import uuid_of, model_settings, model_refs
        expected=Path(source).read_text(encoding='utf-8')
        io=self.pcbnew.PCB_IO_KICAD_SEXPR()
        board=self.pcbnew.LoadBoard(str(source))
        if board is None: raise ValueError('KiCad rejected the relinked PCB')
        if not isinstance(board,self.pcbnew.BOARD): raise ValueError('Parser did not return a BOARD')
        board.thisown=False
        self._detached.append(board)
        with tempfile.TemporaryDirectory(prefix='embed_3d_plugin-roundtrip-') as tmp:
            path=Path(tmp)/'roundtrip.kicad_pcb'; io.SaveBoard(str(path),board)
            actual=path.read_text(encoding='utf-8')
        expected_pool, expected_fragments = _asset_snapshot(expected)
        actual_pool, actual_fragments = _asset_snapshot(actual)
        self.check_payloads(expected_pool,actual_pool)
        def identity(fragment):
            node = parse(fragment)
            models = node.nodes(fragment, 'model')
            payload = node.one(fragment, 'embedded_files')
            return uuid_of(fragment, node), (
                node.arg().value(fragment),
                [(model.arg().value(fragment), semantic(model.raw(fragment), True)) for model in models],
                '(footprint "payloads"\n' + (payload.raw(fragment) if payload else '') + '\n)')
        a = dict(identity(raw) for raw in expected_fragments)
        b = dict(identity(raw) for raw in actual_fragments)
        if set(a)!=set(b): raise ValueError('Native round-trip changed footprint UUIDs')
        for uid in a:
            if a[uid][0] != b[uid][0]:
                raise ValueError('Native round-trip changed a library ID')
            if a[uid][1] != b[uid][1]:
                raise ValueError('Native round-trip changed 3D settings or paths')
            self.check_payloads(a[uid][2], b[uid][2])
        self._release_scratch(board)
        board=None; io=None
