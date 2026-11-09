"""Pure-Python project scanner and self-contained HTML composer."""
from __future__ import annotations

import base64
import datetime
import hashlib
import html
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable


MAX_INPUT_BYTES = 64 * 1024 * 1024
SUPPORTED_MODEL_SUFFIXES = {".wrl", ".glb", ".gltf"}
UNSUPPORTED_MODEL_SUFFIXES = {".step", ".stp", ".iges", ".igs"}
VIEWER_VERSION = "0.1.0-beta.2"
EXPORTER_VERSION = "0.1.0"


@dataclass(frozen=True)
class ComponentRecord:
    reference: str
    value: str = ""
    footprint: str = ""
    board_uuid: str = ""
    schematic_uuids: tuple[str, ...] = ()
    fitted: bool = True

    @property
    def stable_id(self) -> str:
        return self.board_uuid or (self.schematic_uuids[0] if self.schematic_uuids else self.reference)


@dataclass(frozen=True)
class ModelRecord:
    source: str
    resolved: Path | None
    supported: bool
    reason: str = ""
    bundled_path: str = ""


@dataclass
class ProjectScan:
    board: Path
    project_root: Path
    schematics: list[Path] = field(default_factory=list)
    components: list[ComponentRecord] = field(default_factory=list)
    models: list[ModelRecord] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    project_id: str = ""


@dataclass(frozen=True)
class ExportSelection:
    include_schematic: bool = True
    include_pcb: bool = True
    include_bom: bool = True
    include_3d: bool = True
    schematic_paths: tuple[Path, ...] = ()
    model_sources: tuple[str, ...] = ()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        value = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        value = path.name
    return str(PurePosixPath(value))


def _unescape(value: str) -> str:
    return value.replace(r'\"', '"').replace(r"\\", "\\")


def _blocks(text: str, kind: str) -> Iterable[str]:
    marker = "(" + kind
    start = 0
    length = len(text)
    while True:
        index = text.find(marker, start)
        if index < 0:
            return
        after = index + len(marker)
        if after < length and not text[after].isspace() and text[after] != ")":
            start = after
            continue
        depth = 0
        quoted = False
        escaped = False
        for cursor in range(index, length):
            char = text[cursor]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    yield text[index:cursor + 1]
                    start = cursor + 1
                    break
        else:
            return


def _property(block: str, name: str) -> str:
    match = re.search(r'\(property\s+"' + re.escape(name) + r'"\s+"((?:\\.|[^"\\])*)"', block)
    return _unescape(match.group(1)) if match else ""


def _uuid(block: str) -> str:
    match = re.search(r"\(uuid\s+([0-9a-fA-F-]{8,})\)", block)
    return match.group(1) if match else ""


def _schematic_children(path: Path) -> list[Path]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names = re.findall(r'\(property\s+"Sheetfile"\s+"((?:\\.|[^"\\])+)"', text)
    return [(path.parent / _unescape(name)).resolve() for name in names]


def discover_schematics(root: Path) -> tuple[list[Path], list[str]]:
    pending = [root.resolve()]
    found: list[Path] = []
    issues: list[str] = []
    seen: set[Path] = set()
    while pending:
        current = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        if not current.is_file():
            issues.append(f"Missing schematic sheet: {current.name}")
            continue
        found.append(current)
        pending.extend(child for child in _schematic_children(current) if child not in seen)
    return found, issues


def _resolve_model(source: str, root: Path) -> Path | None:
    expanded = source.replace("${KIPRJMOD}", str(root))
    expanded = re.sub(
        r"\$\{([^}]+)\}",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        expanded,
    )
    if "${" in expanded:
        return None
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def scan_project(board_path: str | Path) -> ProjectScan:
    board = Path(board_path).resolve()
    root = board.parent
    scan = ProjectScan(board=board, project_root=root)
    if not board.is_file():
        scan.issues.append(f"Missing PCB file: {board}")
        return scan
    root_schematic = board.with_suffix(".kicad_sch")
    if root_schematic.is_file():
        scan.schematics, issues = discover_schematics(root_schematic)
        scan.issues.extend(issues)
    else:
        scan.issues.append("No root schematic with the PCB base name was found.")

    board_text = board.read_text(encoding="utf-8", errors="replace")
    schematic_by_reference: dict[str, list[str]] = {}
    for schematic in scan.schematics:
        text = schematic.read_text(encoding="utf-8", errors="replace")
        for block in _blocks(text, "symbol"):
            reference = _property(block, "Reference")
            if reference and not reference.startswith("#"):
                identity = _uuid(block)
                if identity:
                    schematic_by_reference.setdefault(reference, []).append(identity)

    models: dict[str, ModelRecord] = {}
    for block in _blocks(board_text, "footprint"):
        reference = _property(block, "Reference")
        if not reference or reference.startswith("#"):
            continue
        value = _property(block, "Value")
        library_match = re.match(r'\(footprint\s+"((?:\\.|[^"\\])*)"', block)
        footprint = _unescape(library_match.group(1)) if library_match else ""
        fitted = "(attr" not in block or "dnp" not in block
        scan.components.append(ComponentRecord(
            reference=reference,
            value=value,
            footprint=footprint,
            board_uuid=_uuid(block),
            schematic_uuids=tuple(sorted(set(schematic_by_reference.get(reference, [])))),
            fitted=fitted,
        ))
        for match in re.finditer(r'\(model\s+"((?:\\.|[^"\\])*)"', block):
            source = _unescape(match.group(1))
            suffix = Path(source).suffix.casefold()
            resolved = _resolve_model(source, root)
            supported = suffix in SUPPORTED_MODEL_SUFFIXES
            reason = ""
            if suffix in UNSUPPORTED_MODEL_SUFFIXES:
                reason = "STEP/IGES decoding is not available in the portable viewer"
            elif not supported:
                reason = f"unsupported model format {suffix or '(none)'}"
            elif resolved is None:
                reason = "an environment variable in the model path is unresolved"
            elif not resolved.is_file():
                reason = "model file is missing"
            if resolved is None or not resolved.is_file():
                supported = False
            models[source] = ModelRecord(source, resolved, supported, reason)
    scan.models = sorted(models.values(), key=lambda item: item.source.casefold())
    for model in scan.models:
        if not model.supported:
            scan.issues.append(f"3D model {model.source}: {model.reason}")

    scan.components.sort(key=lambda item: item.reference.casefold())
    identity_seed = board.stem + "\0" + re.search(r"\(uuid\s+([0-9a-fA-F-]+)\)", board_text).group(1) \
        if re.search(r"\(uuid\s+([0-9a-fA-F-]+)\)", board_text) else board.stem
    scan.project_id = _sha256(identity_seed.encode("utf-8"))[:24]
    return scan


def viewer_asset_dir(package_root: Path) -> Path:
    configured = os.environ.get("WAYRICAD_KICAD_WEBVIEW_DIST")
    return Path(configured).resolve() if configured else package_root / "vendor" / "kicad-webview"


def load_viewer_assets(package_root: Path) -> tuple[str, str]:
    root = viewer_asset_dir(package_root)
    script = root / "kicad-webview.min.js"
    notice_names = (
        "LICENSE", "LICENSING.md", "THIRD-PARTY-NOTICES.md", "THREE-LICENSE",
        "FZSTD-LICENSE", "SPIKE-ENGINE-NOTICE.md", "SOURCE-PROVENANCE.json", "RELEASE.json",
        "licenses/Pocket-KiView-Source-Available-1.0.txt",
    )
    missing = [name for name in ("kicad-webview.min.js", "LICENSE", "THIRD-PARTY-NOTICES.md")
               if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "The pinned KiCad WebView distribution is incomplete: " + ", ".join(missing) +
            ". Reinstall this plugin or set WAYRICAD_KICAD_WEBVIEW_DIST to a reviewed distribution."
        )
    release_path = root / "RELEASE.json"
    if not release_path.is_file():
        raise FileNotFoundError("The pinned KiCad WebView RELEASE.json provenance manifest is missing.")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    if release.get("version") != VIEWER_VERSION:
        raise ValueError(
            f"KiCad WebView version mismatch: expected {VIEWER_VERSION}, found {release.get('version')!r}."
        )
    expected = {item["path"]: item for item in release.get("files", []) if isinstance(item, dict)}
    verified_names = (
        "kicad-webview.min.js", "LICENSE", "LICENSING.md", "THIRD-PARTY-NOTICES.md",
        "THREE-LICENSE", "FZSTD-LICENSE", "SPIKE-ENGINE-NOTICE.md", "SOURCE-PROVENANCE.json",
        "licenses/Pocket-KiView-Source-Available-1.0.txt",
    )
    for name in verified_names:
        path = root / name
        if not path.is_file():
            continue
        record = expected.get(name)
        if not record or record.get("bytes") != path.stat().st_size or record.get("sha256") != _sha256(path.read_bytes()):
            raise ValueError(f"KiCad WebView asset failed pinned release verification: {name}")
    notices = []
    for name in notice_names:
        path = root / name
        if path.is_file():
            notices.append(f"===== {name} =====\n{path.read_text(encoding='utf-8', errors='replace')}")
    return script.read_text(encoding="utf-8"), "\n\n".join(notices)


def estimate_export_size(scan: ProjectScan, selection: ExportSelection, viewer_bytes: int) -> int:
    paths: list[Path] = []
    if selection.include_pcb or selection.include_3d or selection.include_bom:
        paths.append(scan.board)
    if selection.include_schematic:
        paths.extend(selection.schematic_paths)
    if selection.include_3d:
        chosen = set(selection.model_sources)
        paths.extend(model.resolved for model in scan.models
                     if model.supported and model.resolved and model.source in chosen)
    raw = sum(path.stat().st_size for path in dict.fromkeys(paths) if path and path.is_file())
    return int(raw * 4 / 3) + viewer_bytes + 180_000 + len(scan.components) * 450


def _selected_files(scan: ProjectScan, selection: ExportSelection) -> tuple[list[tuple[str, bytes]], list[dict]]:
    files: list[tuple[str, bytes]] = []
    selected_models = set(selection.model_sources)
    replacements: dict[str, str] = {}
    model_manifest: list[dict] = []
    if selection.include_3d:
        for model in scan.models:
            if not model.supported or not model.resolved:
                continue
            if model.source not in selected_models:
                continue
            bundled = f"models/{_sha256(model.source.encode('utf-8'))[:12]}-{model.resolved.name}"
            replacements[model.source] = bundled
            files.append((bundled, model.resolved.read_bytes()))
            model_manifest.append({"source": model.source, "path": bundled})
    if selection.include_pcb or selection.include_3d or selection.include_bom:
        board_text = scan.board.read_text(encoding="utf-8", errors="strict")
        for source, bundled in replacements.items():
            board_text = board_text.replace(f'(model "{source}"', f'(model "{bundled}"')
        files.append((_relative_path(scan.board, scan.project_root), board_text.encode("utf-8")))
    if selection.include_schematic:
        for path in selection.schematic_paths:
            files.append((_relative_path(path, scan.project_root), path.read_bytes()))
    return files, model_manifest


def _component_payload(components: Iterable[ComponentRecord]) -> list[dict]:
    return [{
        "id": item.stable_id,
        "reference": item.reference,
        "value": item.value,
        "footprint": item.footprint,
        "boardUuid": item.board_uuid,
        "schematicUuids": list(item.schematic_uuids),
        "fitted": item.fitted,
        "group": _sha256((item.value + "\0" + item.footprint).encode("utf-8"))[:16],
    } for item in components]


def build_export(scan: ProjectScan, selection: ExportSelection, package_root: Path) -> tuple[str, dict]:
    viewer_script, notices = load_viewer_assets(package_root)
    files, model_manifest = _selected_files(scan, selection)
    if not files:
        raise ValueError("Select at least one schematic sheet or the PCB layout.")
    total = sum(len(data) for _, data in files)
    if total > MAX_INPUT_BYTES:
        raise ValueError(f"Selected design assets total {total / 1024 / 1024:.1f} MiB; the portable viewer limit is 64 MiB.")
    revision_hash = hashlib.sha256()
    payload = []
    source_files = []
    for path, data in sorted(files):
        if path.startswith("/") or ".." in PurePosixPath(path).parts or "\\" in path:
            raise ValueError(f"Unsafe bundled path: {path}")
        revision_hash.update(path.encode("utf-8") + b"\0" + data)
        payload.append({"path": path, "base64": base64.b64encode(data).decode("ascii")})
        source_files.append({"path": path, "bytes": len(data), "sha256": _sha256(data)})
    revision_id = revision_hash.hexdigest()[:24]
    generated_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    document_id = _sha256(f"{scan.project_id}\0{revision_id}\0{generated_at}".encode("utf-8"))[:24]
    manifest = {
        "schema": 1,
        "exporter": f"WayriCAD Portable Web Export {EXPORTER_VERSION}",
        "viewer": f"KiCad WebView {VIEWER_VERSION}",
        "title": scan.board.stem,
        "projectId": scan.project_id,
        "revisionId": revision_id,
        "documentId": document_id,
        "generatedAt": generated_at,
        "boardPath": _relative_path(scan.board, scan.project_root),
        "sheets": [_relative_path(path, scan.project_root) for path in selection.schematic_paths]
            if selection.include_schematic else [],
        "tabs": {
            "schematic": selection.include_schematic,
            "pcb": selection.include_pcb,
            "threeD": selection.include_3d,
            "bom": selection.include_bom,
        },
        "components": _component_payload(scan.components) if selection.include_bom else [],
        "models": model_manifest,
        "sourceFiles": source_files,
        "storageKey": f"wayricad:portable:{scan.project_id}:{revision_id}",
    }
    document = _render_html(viewer_script, notices, payload, manifest)
    return document, manifest


def export_html(scan: ProjectScan, selection: ExportSelection, destination: Path, package_root: Path) -> dict:
    document, manifest = build_export(scan, selection, package_root)
    write_export_document(document, destination)
    return manifest


def write_export_document(document: str, destination: Path) -> None:
    """Atomically persist the exact HTML bytes that were reviewed in preview."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(document, encoding="utf-8", newline="\n")
    os.replace(temporary, destination)


def _json_script(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _render_html(viewer_script: str, notices: str, files: list[dict], manifest: dict) -> str:
    safe_viewer = viewer_script.replace("</script", "<\\/script")
    safe_title = html.escape(manifest["title"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="{html.escape(manifest['exporter'])}"><meta name="wayricad-viewer" content="{html.escape(manifest['viewer'])}">
<meta name="dcterms.created" content="{manifest['generatedAt']}"><meta name="wayricad-project-id" content="{manifest['projectId']}">
<meta name="wayricad-revision-id" content="{manifest['revisionId']}"><meta name="wayricad-document-id" content="{manifest['documentId']}">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; worker-src blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>{safe_title} · WayriCAD review</title>
<style>{_SHELL_CSS}</style></head><body>
<header><div><strong>{safe_title}</strong><span>Revision {manifest['revisionId']} · {manifest['generatedAt']}</span></div><nav id="tabs" aria-label="Views"></nav><button id="about" title="License, source and storage details">About</button></header>
<main><aside><label class="search">Search components<input id="search" type="search" placeholder="Reference, value, footprint"></label><section id="hierarchy"><h2>Sheets</h2><div id="sheets"></div></section><section><h2>Selection</h2><div id="selection">Nothing selected</div></section><section><h2>Progress</h2><div id="progress"></div></section></aside>
<section id="workspace"><div id="viewer" aria-label="Interactive KiCad viewer"></div><section id="bom" hidden><div class="toolbar"><label>Rows <select id="bom-mode"><option value="group">Grouped parts</option><option value="individual">Individual references</option></select></label><button id="backup">Export progress JSON</button><label class="file-button">Import progress JSON<input id="restore" type="file" accept="application/json,.json"></label><label><input id="migrate" type="checkbox"> Allow explicit revision migration</label></div><div class="table-wrap"><table><thead id="bom-head"></thead><tbody id="bom-body"></tbody></table></div><p class="hint">Individual edits save immediately. Group edits are staged until <b>Apply group</b> is pressed and then update every reference in that row.</p></section></section></main>
<footer><span id="status">Opening bundled design…</span><span>Read-only KiCad data · tracking stays in this browser unless exported</span></footer>
<dialog id="about-dialog"><form method="dialog"><button class="close">Close</button><h1>Portable Web Export</h1><p>This HTML contains the selected saved design files and the viewer. It makes no network requests. Procurement and assembly progress is stored in browser local storage under this exact project and revision. Editing progress does not rewrite this downloaded HTML file.</p><dl><dt>Document ID</dt><dd>{manifest['documentId']}</dd><dt>Project ID</dt><dd>{manifest['projectId']}</dd><dt>Revision ID</dt><dd>{manifest['revisionId']}</dd><dt>Generated UTC</dt><dd>{manifest['generatedAt']}</dd><dt>Exporter</dt><dd>{manifest['exporter']}</dd><dt>Viewer</dt><dd>{manifest['viewer']}</dd></dl><details><summary>Embedded source hashes</summary><pre>{html.escape(json.dumps(manifest['sourceFiles'], indent=2))}</pre></details><pre>{html.escape(notices)}</pre></form></dialog>
<script type="application/json" id="wayricad-export-metadata">{_json_script(manifest)}</script>
<script>{safe_viewer}</script><script>
const MANIFEST={_json_script(manifest)};const BUNDLED={_json_script(files)};
{_SHELL_JS}
</script></body></html>'''


_SHELL_CSS = r'''
:root{color-scheme:dark;--bg:#111820;--panel:#18222c;--line:#344655;--text:#e6edf3;--muted:#9aa9b7;--accent:#2c9a87;--warn:#d59a3b}*{box-sizing:border-box}html,body{height:100%;margin:0;font:14px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--text)}body{display:grid;grid-template-rows:auto 1fr auto;min-width:300px}header{display:flex;align-items:center;gap:16px;padding:8px 12px;border-bottom:1px solid var(--line);background:#151f28}header>div{min-width:180px}header strong,header span{display:block}header span{font-size:11px;color:var(--muted)}nav{display:flex;gap:4px;flex:1;overflow:auto}button,.file-button,select,input{font:inherit;color:inherit;background:#202d38;border:1px solid #526776;border-radius:4px;min-height:34px;padding:6px 9px}button,.file-button{cursor:pointer}button:hover,.file-button:hover{border-color:#74a2b8}.active{background:var(--accent);border-color:var(--accent);color:white}main{display:grid;grid-template-columns:minmax(210px,280px) 1fr;min-height:0}aside{overflow:auto;border-right:1px solid var(--line);padding:12px;background:var(--panel)}aside h2{font-size:12px;text-transform:uppercase;color:var(--muted);margin:18px 0 6px}.search input{display:block;width:100%;margin-top:5px}.sheet{display:block;width:100%;text-align:left;margin:3px 0}.sheet small{display:block;color:var(--muted)}#workspace{min-width:0;min-height:0;position:relative}#viewer{width:100%;height:100%;min-height:320px}#bom{height:100%;overflow:hidden;display:flex;flex-direction:column}#bom[hidden]{display:none}.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:9px;border-bottom:1px solid var(--line)}.file-button input{display:none}.table-wrap{overflow:auto;flex:1}table{border-collapse:collapse;width:100%;min-width:1050px}th,td{padding:7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}th{position:sticky;top:0;background:#202d38;z-index:1}tbody tr:hover{background:#1d2b35}tbody tr.selected{outline:2px solid var(--accent);outline-offset:-2px}td input,td select{width:100%;min-width:70px}.refs{max-width:260px;white-space:normal}.hint{padding:6px 12px;color:var(--muted);margin:0;border-top:1px solid var(--line)}footer{display:flex;justify-content:space-between;gap:12px;padding:5px 12px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}dialog{max-width:min(900px,94vw);max-height:85vh;background:var(--panel);color:var(--text);border:1px solid var(--line)}dialog pre{white-space:pre-wrap;font:11px/1.4 monospace}.close{float:right}.metric{display:flex;justify-content:space-between;padding:3px 0}.badge{display:inline-block;padding:2px 5px;border-radius:3px;background:#2c3d49;color:var(--muted)}@media(max-width:760px){header{align-items:flex-start;flex-wrap:wrap}header>div{width:100%}main{grid-template-columns:1fr;grid-template-rows:auto 1fr}aside{border-right:0;border-bottom:1px solid var(--line);max-height:185px;display:grid;grid-template-columns:1fr 1fr;gap:0 14px}aside .search{grid-column:1/-1}aside h2{margin-top:7px}#hierarchy{max-height:90px;overflow:auto}footer{display:block}footer span{display:block}}
'''


_SHELL_JS = r'''
const decode=file=>({path:file.path,bytes:Uint8Array.from(atob(file.base64),c=>c.charCodeAt(0))});
const files=BUNDLED.map(decode),status=document.querySelector('#status'),viewerEl=document.querySelector('#viewer'),bomEl=document.querySelector('#bom');
const viewer=new KiCadWebView.Viewer('#viewer',{theme:'dark',inspectOnSelect:false});let activeTab='',selectedId='';
const componentById=new Map(MANIFEST.components.map(c=>[c.id,c]));const byRef=new Map(MANIFEST.components.map(c=>[c.reference,c]));
const emptyState=()=>({schema:1,projectId:MANIFEST.projectId,revisionId:MANIFEST.revisionId,updated:new Date().toISOString(),components:{}});
let progress=emptyState();try{const saved=localStorage.getItem(MANIFEST.storageKey);if(saved){const parsed=JSON.parse(saved);if(parsed.projectId===MANIFEST.projectId&&parsed.revisionId===MANIFEST.revisionId)progress=parsed;}}catch(error){status.textContent='Browser storage is unavailable; use progress JSON backup.';}
function record(id){return progress.components[id]||={orderedQty:0,receivedQty:0,assembly:'not-started',dnp:false,notes:''};}
function save(){progress.updated=new Date().toISOString();try{localStorage.setItem(MANIFEST.storageKey,JSON.stringify(progress));status.textContent='Progress saved in this browser for this exact revision.';}catch(error){status.textContent='Could not save browser progress. Export a JSON backup.';}renderSummary();}
function renderSummary(){const rows=MANIFEST.components.map(c=>record(c.id)),ordered=rows.reduce((n,r)=>n+Number(r.orderedQty||0),0),received=rows.reduce((n,r)=>n+Number(r.receivedQty||0),0),assembled=rows.filter(r=>r.assembly==='complete').length;document.querySelector('#progress').innerHTML=`<div class="metric"><span>References</span><b>${rows.length}</b></div><div class="metric"><span>Ordered</span><b>${ordered}</b></div><div class="metric"><span>Received</span><b>${received}</b></div><div class="metric"><span>Assembly complete</span><b>${assembled}</b></div>`;}
function tab(name,label){const button=document.createElement('button');button.textContent=label;button.dataset.tab=name;button.onclick=()=>openTab(name);document.querySelector('#tabs').append(button);}
if(MANIFEST.tabs.schematic)tab('schematic','Schematic');if(MANIFEST.tabs.pcb)tab('pcb','PCB Layout');if(MANIFEST.tabs.threeD)tab('3d','3D');if(MANIFEST.tabs.bom)tab('bom','BoM & Tracking');tab('notices','Notices');
function openTab(name){activeTab=name;document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));bomEl.hidden=name!=='bom';viewerEl.hidden=name==='bom'||name==='notices';if(name==='notices'){document.querySelector('#about-dialog').showModal();openTab(MANIFEST.tabs.pcb?'pcb':MANIFEST.tabs.schematic?'schematic':MANIFEST.tabs.threeD?'3d':'bom');return;}if(name==='bom'){renderBom();return;}viewer.setView(name).catch(error=>status.textContent=error.message);}
function openSheet(path){viewer.openFile(path).then(()=>viewer.setView('schematic')).then(()=>openTab('schematic')).catch(error=>status.textContent=error.message);}
const sheets=document.querySelector('#sheets');MANIFEST.sheets.forEach(path=>{const button=document.createElement('button');button.className='sheet';button.innerHTML=`${path.split('/').pop()}<small>${path}</small>`;button.onclick=()=>openSheet(path);sheets.append(button);});if(!MANIFEST.sheets.length)document.querySelector('#hierarchy').hidden=true;
function findViewerPart(component){const parts=viewer.getParts?.()||[];const ids=[component.boardUuid,...component.schematicUuids,component.id].filter(Boolean);return parts.find(p=>ids.includes(p.uuid)||ids.includes(p.id))||parts.find(p=>(p.reference||p.ref)===component.reference);}
function focusComponent(component){selectedId=component.id;const part=findViewerPart(component);if(part){viewer.selectPart(part.uuid||part.id||part.reference||part.ref,{locate:true});document.querySelector('#selection').innerHTML=`<b>${component.reference}</b><br>${component.value||'No value'}<br><span class="badge">${component.footprint||'No footprint'}</span>`;if(activeTab==='bom')openTab(MANIFEST.tabs.pcb?'pcb':MANIFEST.tabs.schematic?'schematic':'3d');}else status.textContent=`${component.reference} is listed in the BoM but has no resolved identity in the active view.`;}
viewer.addEventListener('select',event=>{const item=event.detail?.item||{},ids=[item.uuid,item.id].filter(Boolean),component=MANIFEST.components.find(c=>ids.includes(c.boardUuid)||c.schematicUuids.some(id=>ids.includes(id)))||byRef.get(item.reference||item.ref);if(component){selectedId=component.id;document.querySelector('#selection').textContent=`${component.reference} · ${component.value}`;document.querySelectorAll('#bom-body tr').forEach(row=>row.classList.toggle('selected',row.dataset.ids?.split(',').includes(component.id)));}});
viewer.addEventListener('error',event=>status.textContent=event.detail?.message||'Viewer error');
const loadView=MANIFEST.tabs.pcb?'pcb':MANIFEST.tabs.schematic?'schematic':MANIFEST.tabs.threeD?'3d':'pcb',initial=MANIFEST.tabs.pcb?'pcb':MANIFEST.tabs.schematic?'schematic':MANIFEST.tabs.threeD?'3d':'bom';viewer.loadFiles(files,{view:loadView}).then(()=>{status.textContent='Offline · read-only design · no network access';openTab(initial);}).catch(error=>status.textContent=error.message);
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function filtered(){const query=document.querySelector('#search').value.trim().toLowerCase();return MANIFEST.components.filter(c=>!query||`${c.reference} ${c.value} ${c.footprint}`.toLowerCase().includes(query));}
function field(value,name,type='text'){if(name==='assembly')return `<select data-field="assembly"><option value="not-started"${value==='not-started'?' selected':''}>Not started</option><option value="in-progress"${value==='in-progress'?' selected':''}>In progress</option><option value="complete"${value==='complete'?' selected':''}>Complete</option><option value="blocked"${value==='blocked'?' selected':''}>Blocked</option></select>`;if(type==='checkbox')return `<input data-field="${name}" type="checkbox"${value?' checked':''}>`;return `<input data-field="${name}" type="${type}" value="${esc(value)}" ${type==='number'?'min="0" step="1"':''}>`;}
function renderBom(){const grouped=document.querySelector('#bom-mode').value==='group',body=document.querySelector('#bom-body');document.querySelector('#bom-head').innerHTML='<tr><th>References</th><th>Value</th><th>Footprint</th><th>Qty</th><th>Ordered</th><th>Received</th><th>Assembly</th><th>DNP</th><th>Notes</th><th>Action</th></tr>';body.innerHTML='';let rows;if(grouped){const groups=new Map;filtered().forEach(c=>{if(!groups.has(c.group))groups.set(c.group,[]);groups.get(c.group).push(c);});rows=[...groups.values()];}else rows=filtered().map(c=>[c]);rows.forEach(items=>{const first=items[0],ids=items.map(c=>c.id),states=items.map(c=>record(c.id)),common=(name,fallback)=>states.every(s=>String(s[name])===String(states[0][name]))?states[0][name]:fallback,tr=document.createElement('tr');tr.dataset.ids=ids.join(',');tr.classList.toggle('selected',ids.includes(selectedId));tr.innerHTML=`<td class="refs"><button data-focus="${esc(first.id)}">${esc(items.map(c=>c.reference).join(', '))}</button></td><td>${esc(first.value)}</td><td>${esc(first.footprint)}</td><td>${items.length}</td><td>${field(common('orderedQty',''),'orderedQty','number')}</td><td>${field(common('receivedQty',''),'receivedQty','number')}</td><td>${field(common('assembly','not-started'),'assembly')}</td><td>${field(Boolean(common('dnp',false)),'dnp','checkbox')}</td><td>${field(common('notes',''),'notes')}</td><td>${grouped?'<button data-apply>Apply group</button>':'Saved immediately'}</td>`;body.append(tr);tr.querySelector('[data-focus]').onclick=()=>focusComponent(componentById.get(first.id));const commit=()=>{tr.querySelectorAll('[data-field]').forEach(input=>ids.forEach(id=>record(id)[input.dataset.field]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value||0):input.value));save();};if(grouped)tr.querySelector('[data-apply]').onclick=()=>{if(confirm(`Apply these tracking values to all ${ids.length} references in this group?`))commit();};else tr.querySelectorAll('[data-field]').forEach(input=>input.onchange=commit);});}
document.querySelector('#search').oninput=()=>{if(activeTab==='bom')renderBom();};document.querySelector('#bom-mode').onchange=renderBom;
document.querySelector('#backup').onclick=()=>{const blob=new Blob([JSON.stringify(progress,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`${MANIFEST.title}-${MANIFEST.revisionId}-progress.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);};
document.querySelector('#restore').onchange=async event=>{try{const imported=JSON.parse(await event.target.files[0].text());if(imported.projectId!==MANIFEST.projectId)throw Error('This backup belongs to a different project.');const migrating=imported.revisionId!==MANIFEST.revisionId;if(migrating&&!document.querySelector('#migrate').checked)throw Error('Revision differs. Enable explicit revision migration to import matching stable component identities.');const next=emptyState();for(const [id,value] of Object.entries(imported.components||{}))if(componentById.has(id))next.components[id]=value;progress=next;save();renderBom();status.textContent=migrating?'Imported matching identities from another revision; review all migrated rows.':'Progress backup restored.';}catch(error){status.textContent='Import rejected: '+error.message;}finally{event.target.value='';}};
document.querySelector('#about').onclick=()=>document.querySelector('#about-dialog').showModal();renderSummary();window.addEventListener('pagehide',()=>viewer.dispose(),{once:true});
'''
