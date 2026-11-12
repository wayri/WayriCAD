/* Read-only KiView integration. Host messages carry data, never executable code.
 * Projection adapter is pinned to owned-canvas Camera methods and board3d's
 * projectAnchor API. Do not replace unavailable mappings with guessed pixels.
 */
const NS = 'http://www.w3.org/2000/svg';
const LIMIT = 1e6;
export const MARKER_COLORS = Object.freeze({normal:'#087f8c', selected:'#915700', error:'#b53434', draftLight:'#915700', draftDark:'#ffd08a'});
const object = value => value && typeof value === 'object' && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
function fields(value, keys) {
  if (!object(value) || Object.keys(value).some(key => !keys.includes(key))) throw new TypeError('Unsupported bridge payload fields.');
}
function text(value, max = 500) {
  if (typeof value !== 'string' || !value || value.length > max || /[\x00-\x1f\x7f]/.test(value)) throw new TypeError('Invalid bridge text.');
  return value;
}
function number(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > LIMIT) throw new TypeError('Invalid world coordinate.');
  return value;
}
function point(value) {
  fields(value, ['x', 'y']);
  return { x: number(value.x), y: number(value.y) };
}
export function canonicalScope(value) {
  fields(value, ['repository', 'ref', 'file', 'provider', 'host']);
  const provider = value.provider || 'github', repository = text(value.repository), file = text(value.file);
  if (!['github', 'gitlab'].includes(provider) || !/^[a-f0-9]{40}$/i.test(value.ref)) throw new TypeError('An immutable review scope is required.');
  const parts = repository.split('/');
  if (parts.length < 2 || provider === 'github' && parts.length !== 2 ||
      parts.some(part => !/^[A-Za-z0-9_.-]+$/.test(part) || ['.', '..'].includes(part))) throw new TypeError('Invalid review repository.');
  if (/[\\:]/.test(file) || file.startsWith('/') || file.split('/').some(part => ['', '.', '..'].includes(part)) ||
      !/\.kicad_(pcb|sch)$/i.test(file)) throw new TypeError('Invalid review design path.');
  const result = { repository, ref: value.ref.toLowerCase(), file };
  if (provider === 'gitlab') {
    const raw = value.host || 'https://gitlab.com', address = new URL(raw);
    const origin = /^https:\/\/([^/?#]+)\/?$/.exec(raw);
    if (address.protocol !== 'https:' || address.username || address.password || !['', '/'].includes(address.pathname) || address.search || address.hash) throw new TypeError('Invalid GitLab origin.');
    if (!origin || /[\s\\\x00-\x1f]/.test(raw)) throw new TypeError('Invalid GitLab origin.');
    result.provider = provider; result.host = `https://${origin[1].toLowerCase()}`;
  }
  return result;
}
const sameScope = (left, right) => Boolean(left && right && JSON.stringify(canonicalScope(left)) === JSON.stringify(canonicalScope(right)));
export function validateAnchor(value, expected) {
  fields(value, ['repository', 'ref', 'file', 'provider', 'host', 'uuid', 'objectId', 'reference', 'netName', 'kind', 'variant', 'position', 'area', 'context']);
  const target = canonicalScope(Object.fromEntries(['repository', 'ref', 'file', 'provider', 'host'].filter(key => key in value).map(key => [key, value[key]])));
  if (!sameScope(target, expected)) throw new TypeError('Anchor belongs to another design or revision.');
  for (const [key, limit] of Object.entries({uuid:200, objectId:200, reference:100, netName:500, kind:80, variant:100})) if (key in value) {
    target[key] = text(value[key], limit).trim(); if (!target[key]) throw new TypeError('Invalid anchor text.');
  }
  if ('position' in value) target.position = point(value.position);
  if ('area' in value) {
    fields(value.area, ['x', 'y', 'width', 'height']);
    target.area = Object.fromEntries(['x', 'y', 'width', 'height'].map(key => [key, number(value.area[key])]));
    if (!(target.area.width > 0 && target.area.height > 0)) throw new TypeError('A region needs positive dimensions.');
  }
  if ('context' in value) {
    target.context = validateArtifact(value.context);
    if ('position' in value || 'area' in value) throw new TypeError('Manufacturing coordinates must remain in artifact context.');
  }
  return target;
}
const gerberPath = value => typeof value === 'string' && value.length <= 500 && !/[\\:\x00-\x1f\x7f]/.test(value) && !value.startsWith('/') && value.split('/').every(p=>p && p!=='.' && p!=='..') && /\.(gbr|ger|gerber|gtl|gbl|gts|gbs|gto|gbo|gtp|gbp|gm1|gko|drl)$/i.test(value);
function validateArtifact(value) {
  fields(value,['type','file','sha256','position','area']);
  if(value.type!=='gerber' || !gerberPath(value.file) || !/^[a-f0-9]{64}$/.test(value.sha256)) throw new TypeError('A bounded project-local manufacturing identity is required.');
  const result={type:'gerber',file:value.file,sha256:value.sha256};
  if(value.position) result.position=point(value.position);
  if(value.area){ fields(value.area,['x','y','width','height']); result.area=Object.fromEntries(['x','y','width','height'].map(k=>[k,number(value.area[k])])); if(result.area.width<=0||result.area.height<=0)throw new TypeError('A region needs positive dimensions.'); }
  if(result.area&&result.position)throw new TypeError('Choose a point or region.');
  return result;
}
export function validateDocument(value) {
  fields(value, ['source', 'path', 'source_sha256', 'scope', 'view', 'documents', 'current_document_id', 'artifact']);
  if (typeof value.source !== 'string' || value.source.length > 64 * 1024 * 1024) throw new TypeError('A bounded saved design source is required.');
  const path = text(value.path), kind = /\.kicad_pcb$/i.test(path) ? 'pcb' : /\.kicad_sch$/i.test(path) ? 'schematic' : gerberPath(path) ? 'manufacturing' : null;
  if (!kind || kind !== 'manufacturing' && !new RegExp('^\\s*\\(kicad_' + (kind === 'pcb' ? 'pcb' : 'sch') + '(?:\\s|\\))').test(value.source)) throw new TypeError('Source and saved design type do not match.');
  if (!/^[a-f0-9]{64}$/i.test(value.source_sha256)) throw new TypeError('A saved source SHA256 is required.');
  const scope = value.scope == null ? null : canonicalScope(value.scope);
  const view = value.view || kind;
  if (!['pcb', 'schematic', '3d', 'manufacturing'].includes(view) || kind === 'manufacturing' && view !== 'manufacturing' || kind === 'schematic' && view !== 'schematic' || kind === 'pcb' && !['pcb','3d'].includes(view)) throw new TypeError('View does not match this design type.');
  const artifact = value.artifact == null ? null : validateArtifact(value.artifact);
  if(artifact && (kind!=='manufacturing' || artifact.sha256!==value.source_sha256)) throw new TypeError('Manufacturing identity differs from its saved bytes.');
  const documents = value.documents || [];
  if (!Array.isArray(documents) || documents.length > 128) throw new TypeError('Project document list is oversized.');
  const seen = new Set();
  const choices = documents.map(entry => {
    fields(entry, ['id', 'label', 'kind']);
    const id = text(entry.id), label = text(entry.label), type = entry.kind;
    if (seen.has(id) || !['pcb', 'schematic', 'manufacturing'].includes(type)) throw new TypeError('Invalid project document choice.');
    seen.add(id); return { id, label, kind: type };
  });
  const current = value.current_document_id == null ? null : text(value.current_document_id);
  if (current && !seen.has(current)) throw new TypeError('Current document is not in the host choices.');
  return { source: value.source, path, source_sha256: value.source_sha256.toLowerCase(), scope, view, kind, documents: choices, current_document_id: current, artifact };
}
export function validateComments(value, document) {
  fields(value, ['scope', 'status', 'markers', 'selected_id', 'path', 'source_sha256']);
  if (value.status !== 'synced' || !document?.scope || !sameScope(value.scope, document.scope)) return [];
  if (!Array.isArray(value.markers) || value.markers.length > 1000) throw new TypeError('Comment marker list is oversized.');
  return value.markers.map(item => {
    fields(item, ['comment_id', 'anchor', 'x', 'y', 'severity', 'state', 'label', 'region']);
    const anchor = validateAnchor(item.anchor, document.scope);
    if(anchor.context && (!document.artifact || anchor.context.file!==document.artifact.file || anchor.context.sha256!==document.artifact.sha256))throw new TypeError('Marker belongs to another manufacturing artifact.');
    if(document.kind==='manufacturing' && !anchor.context)throw new TypeError('Manufacturing markers need artifact context.');
    const geometry=anchor.context||anchor;
    const region = geometry.area ? [geometry.area.x, geometry.area.y, geometry.area.width, geometry.area.height] : null;
    if (item.region != null && (!Array.isArray(item.region) || item.region.length !== 4 || item.region.some((v, i) => number(v) !== region?.[i]))) throw new TypeError('Region does not match its anchor.');
    const position = geometry.position || (region ? { x: region[0]+region[2]/2, y: region[1]+region[3]/2 } : { x: number(item.x), y: number(item.y) });
    if (!anchor.position && !region && !anchor.uuid && !anchor.objectId) throw new TypeError('Comment has no saved location.');
    if (Math.abs(number(item.x)-position.x) > 1e-6 || Math.abs(number(item.y)-position.y) > 1e-6) throw new TypeError('Marker position differs from its anchor.');
    return { comment_id: text(item.comment_id, 200), anchor, ...position, region,
      severity: typeof item.severity === 'string' ? item.severity.slice(0, 40) : 'info',
      state: typeof item.state === 'string' ? item.state.slice(0, 40) : 'open',
      label: typeof item.label === 'string' ? item.label.slice(0, 160) : '' };
  });
}

/** 0.6.0 has no public arbitrary-point 3D projector. Never guess exploded Z. */
export function overlaysRegistered(viewer) {
  if (viewer.view !== '3d') return true;
  try {
    const value = typeof viewer.getExplode === 'function' ? viewer.getExplode() : viewer.renderer?.getExplode?.() ?? 0;
    return Number.isFinite(value) && value === 0;
  } catch { return false; }
}
function camera2D(viewer) {
  const camera = viewer.getCamera?.();
  return camera && [camera.center?.x, camera.center?.y, camera.zoom].every(Number.isFinite) && camera.zoom > 0 && typeof camera.flipped === 'boolean' ? camera : null;
}
/** Public copied 2D camera in CSS pixels/mm; legacy/CAM stays version-pinned. */
export function projectWorld(viewer, position, rect) {
  let projected;
  if (viewer.view === '3d') {
    if (!overlaysRegistered(viewer)) return null;
    projected = viewer.renderer?.projectAnchor?.({ position });
    if (!projected || projected.visible !== true) return null;
    projected = { x: projected.x-rect.left, y: projected.y-rect.top };
  } else if (typeof viewer.getCamera === 'function' && viewer.view !== 'manufacturing') {
    const camera = camera2D(viewer);
    if (!camera) return null;
    projected = {x:(position.x-camera.center.x)*camera.zoom*(camera.flipped?-1:1)+rect.width/2,
      y:(position.y-camera.center.y)*camera.zoom+rect.height/2};
  } else projected = viewer.renderer?.viewport?.camera?.world_to_screen?.(position);
  return projected && [projected.x, projected.y].every(Number.isFinite) ? projected : null;
}
export function screenToWorld(viewer, x, y, rect = viewer.stage?.getBoundingClientRect()) {
  if (viewer.view === '3d') throw new Error('Point and region drafting require the PCB or schematic view; 3D has no verified screen-to-mm inverse.');
  if (typeof viewer.getCamera === 'function' && viewer.view !== 'manufacturing') {
    const camera = camera2D(viewer);
    if (!camera || !rect) throw new Error('The public camera is unavailable.');
    return point({x:camera.center.x+(x-rect.width/2)/camera.zoom*(camera.flipped?-1:1),
      y:camera.center.y+(y-rect.height/2)/camera.zoom});
  }
  const camera = viewer.renderer?.viewport?.camera;
  if (typeof camera?.screen_to_world !== 'function') throw new Error('The renderer has no verified coordinate mapping.');
  return point(camera.screen_to_world({ x, y }));
}

function nativePost(value, target=globalThis) {
  const channel=target.wayricadHost;
  if(typeof channel?.postMessage!=='function') throw new Error('The native Review message handler is unavailable.');
  channel.postMessage(JSON.stringify(value));
}

export function createReviewBridge({ ViewerClass, elements, document: dom = globalThis.document,
  postMessage = value => nativePost(value),
  raf = globalThis.requestAnimationFrame?.bind(globalThis), cancelRaf = globalThis.cancelAnimationFrame?.bind(globalThis) } = {}) {
  if (!elements?.viewer || !dom?.createElementNS) throw new Error('Review viewer container is missing.');
  const viewer = new ViewerClass(elements.viewer, { theme: 'light', loadAsset: async () => { throw new Error('No host-authorized component model asset was supplied.'); } });
  // Version-pinned chrome adapter: KiView's open shadow surface owns this
  // toolbar. Hide only that verified node; the host supplies the controls and
  // its single app theme switch calls the public setTheme API below.
  const libraryToolbar = viewer.surface?.querySelector?.('[role="toolbar"][aria-label="Drawing viewer controls"]');
  if (libraryToolbar) libraryToolbar.style.display = 'none';
  const overlay = elements.overlay || dom.createElementNS(NS, 'svg');
  overlay.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:20';
  let document = null, markers = [], draft = null, selected = null, mode = 'navigate', theme = 'light', layersOpen = false, generation = 0, disposed = false, tick = null, stopHooks = () => {}, drag = null, swallowClick = false;
  let documentLoaded = false, loadController = null, viewController = null, viewGeneration = 0;
  const send = (type, detail = {}) => postMessage({ type, ...detail, ...(document ? { path: document.path, source_sha256: document.source_sha256 } : {}) });
  const status = message => { if (elements.status) elements.status.textContent = String(message); };
  const error = reason => { const message = reason?.message || String(reason); status(message); send('error', { message }); };
  const listen = (element, name, action, options) => element?.addEventListener(name, action, options);
  const safe = operation => (...args) => { try { Promise.resolve(operation(...args)).catch(error); } catch (reason) { error(reason); } };
  const setMode = next => {
    if (!['navigate', 'pin', 'region'].includes(next)) throw new TypeError('Invalid review mode.');
    if (next !== 'navigate' && (!document?.scope || !api.authorized)) throw new Error('Refresh the matching provider conversation before drafting a marker.');
    if (next !== 'navigate' && viewer.view === '3d') throw new Error('Draft points and regions in PCB view; 3D is independent inspection.');
    mode = next; updateModeControls();
    if (elements['comment-menu']) elements['comment-menu'].open = false;
    status(next === 'navigate' ? 'Drag to navigate · click an object or comment' : next === 'pin' ? 'Click to attach a local unpublished point' : 'Drag a local unpublished region');
  };
  function updateModeControls() {
    for (const [id, value] of [['mode-pan','navigate'], ['mode-pin','pin'], ['mode-region','region']]) {
      const button = elements[id];
      if (button) {
        button.setAttribute('aria-pressed', String(mode === value));
        button.disabled = value !== 'navigate' && (!documentLoaded || !api.authorized || viewer.view === '3d');
      }
    }
    if (elements['comment-label']) elements['comment-label'].textContent = mode === 'pin' ? 'Place pin…' : mode === 'region' ? 'Draw region…' : 'Add comment';
  }
  function applyTheme() {
    // setTheme redraws the existing renderer and preserves its camera.
    viewer.setTheme?.(theme);
    dom.documentElement?.setAttribute('data-theme', theme);
  }
  function clearTick() { if (tick != null) cancelRaf?.(tick); tick = null; }
  function clearDrawing() {
    documentLoaded=false;loadController?.abort();viewController?.abort();++viewGeneration;
    clearTick(); stopHooks(); stopHooks=()=>{};
    viewer.pending?.abort(); if (Number.isFinite(viewer.generation)) ++viewer.generation;
    viewer.renderer?.dispose?.(); viewer.renderer=null;
    viewer.source=viewer.design=viewer.kind=viewer.view=null;
    viewer.stage.replaceChildren(overlay); overlay.replaceChildren();
    mode='navigate';drag=null;swallowClick=false;selected=null;draft=null;
    updateTabs();updateLayers();updateDocuments();
  }
  function updateTabs() {
    for (const view of ['pcb', 'schematic', '3d', 'manufacturing']) {
      const button = elements[`view-${view}`];
      if (button) { button.disabled = !documentLoaded || (view === '3d' ? document.kind !== 'pcb' : !document.documents.some(d=>d.kind===view)); button.setAttribute('aria-pressed', String(documentLoaded && viewer.view === view)); }
    }
    updateModeControls();
  }
  function updateLayers() {
    if (!elements.layers) return;
    elements.layers.replaceChildren();
    const hasLayers = ['pcb','manufacturing'].includes(viewer.view) || viewer.view==='3d' && typeof viewer.getLayerState==='function';
    const known = documentLoaded && hasLayers ? viewer.getLayers() : [];
    const visible = viewer.getLayerState?.()?.visible;
    const toggle = elements['layers-toggle'];
    if (toggle) {
      toggle.disabled = !known.length;
      toggle.setAttribute('aria-expanded', String(layersOpen && Boolean(known.length)));
    }
    elements.layers.hidden = !layersOpen || !known.length;
    for (const layer of known) {
      const label = dom.createElement('label'), check = dom.createElement('input');
      check.type = 'checkbox'; check.value = layer; check.checked = Array.isArray(visible) ? visible.includes(layer) : viewer.renderer?.visibleLayers?.has(layer) ?? true;
      label.append(check, dom.createTextNode(layer)); elements.layers.append(label);
      listen(check, 'change', safe(() => viewer.setLayers([...elements.layers.querySelectorAll('input')].filter(input => input.checked).map(input => input.value))));
    }
  }
  function updateDocuments() {
    if (!elements.documents) return;
    elements.documents.replaceChildren();
    for (const item of document?.documents || []) {
      const option = dom.createElement('option'); option.value = item.id; option.textContent = item.label; elements.documents.append(option);
    }
    elements.documents.value = document?.current_document_id || '';
  }
  function shape(name, attributes, label) {
    const element = dom.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    if (label != null) element.textContent = String(label);
    return element;
  }
  function drawOverlay() {
    if (disposed) return;
    overlay.replaceChildren();
    if (!documentLoaded) return;
    const rect = viewer.stage.getBoundingClientRect();
    overlay.setAttribute('viewBox', `0 0 ${Math.max(1, rect.width)} ${Math.max(1, rect.height)}`);
    const registered = overlaysRegistered(viewer);
    if (!registered) overlay.setAttribute('aria-label', 'Review markers hidden: exploded 3D is not registered to saved XY anchors');
    else overlay.setAttribute('aria-label', 'Review comment markers');
    for (const [index, marker] of (registered ? markers : []).entries()) {
      const at = projectWorld(viewer, { x: marker.x, y: marker.y }, rect);
      if (!at) continue;
      const visible=at.x>=-20 && at.y>=-20 && at.x<=rect.width+20 && at.y<=rect.height+20;
      if (!visible && !marker.region) continue;
      const color = marker.comment_id === selected ? MARKER_COLORS.selected : ['error', 'critical'].includes(marker.severity) ? MARKER_COLORS.error : MARKER_COLORS.normal;
      const group = shape('g', { 'data-comment-id': marker.comment_id, tabindex: 0, role: 'button', 'aria-label': marker.label || `Comment ${index+1}` });
      group.style.pointerEvents = 'all';
      if (marker.region) {
        const [x, y, width, height] = marker.region;
        const corners = [{x,y}, {x:x+width,y}, {x:x+width,y:y+height}, {x,y:y+height}].map(p => projectWorld(viewer, p, rect));
        if (corners.every(Boolean)) group.append(shape('polygon', { points: corners.map(p => `${p.x},${p.y}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-dasharray': '5 3' }));
      }
      if(visible) group.append(shape('circle', { cx: at.x, cy: at.y, r: 12, fill: color, stroke: '#fff', 'stroke-width': 2 }),
                               shape('text', { x: at.x, y: at.y+4, 'text-anchor': 'middle', 'font-family': 'sans-serif', 'font-size': 12, fill: 'white' }, index+1));
      listen(group, 'pointerdown', event => event.stopPropagation());
      const focus = event => { event.stopPropagation(); if (!api.authorized || !markers.includes(marker)) return; selected = marker.comment_id; send('focusThread', { comment_id: marker.comment_id }); drawOverlay(); };
      listen(group, 'click', focus); listen(group, 'keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); focus(event); } });
      overlay.append(group);
    }
    if (registered && draft && api.authorized) {
      const group = shape('g', {'data-draft':'true', 'aria-label':'Unpublished comment location'});
      const geometry=draft.context||draft;
      const color = theme === 'dark' ? MARKER_COLORS.draftDark : MARKER_COLORS.draftLight, area = geometry.area;
      const center = area ? {x:area.x+area.width/2,y:area.y+area.height/2} : geometry.position;
      if (area) {
        const corners = [{x:area.x,y:area.y},{x:area.x+area.width,y:area.y},
          {x:area.x+area.width,y:area.y+area.height},{x:area.x,y:area.y+area.height}]
          .map(p=>projectWorld(viewer,p,rect));
        if (corners.every(Boolean)) group.append(shape('polygon',{points:corners.map(p=>`${p.x},${p.y}`).join(' '),
          fill:'none',stroke:color,'stroke-width':3,'stroke-dasharray':'6 4'}));
      }
      const at = projectWorld(viewer,center,rect);
      if (at) group.append(shape('circle',{cx:at.x,cy:at.y,r:15,fill:'none',stroke:color,'stroke-width':3}),
        shape('text',{x:at.x,y:at.y+5,'text-anchor':'middle','font-family':'sans-serif','font-size':16,fill:color},'+'));
      overlay.append(group);
    }
    if (viewer.view === '3d' && (markers.length || draft) && raf && tick == null) {
      tick = raf(() => { tick = null; if (!disposed && viewer.view === '3d') drawOverlay(); });
    }
  }
  function installProjectionHooks() {
    stopHooks(); clearTick(); viewer.stage.append(overlay);
    const renderer = viewer.renderer, originals = [];
    // OwnedCanvas mutates its camera before draw/requestDraw/resize. Observe
    // those calls rather than duplicating the camera transform or wheel math.
    if (typeof viewer.getCamera !== 'function' || viewer.view === 'manufacturing') for (const key of ['draw', 'requestDraw', 'resize']) {
      if (typeof renderer?.[key] !== 'function') continue;
      const original = renderer[key];
      const replacement = function (...args) { const result = original.apply(this, args); drawOverlay(); return result; };
      renderer[key] = replacement; originals.push(() => { if (renderer[key] === replacement) renderer[key] = original; });
    }
    stopHooks = () => originals.forEach(restore => restore());
    drawOverlay(); updateLayers(); updateTabs();
  }
  listen(viewer, 'ready', () => { if (!disposed && documentLoaded) installProjectionHooks(); });
  listen(viewer, 'camerachange', event => { if (documentLoaded && (!event.detail?.path || event.detail.path===document.path)) drawOverlay(); });
  listen(viewer, 'viewchange', () => { if (!disposed && documentLoaded) installProjectionHooks(); });
  listen(viewer, 'layerschange', () => { if (!disposed && documentLoaded) { updateLayers();drawOverlay(); } });
  listen(viewer, 'select', event => {
    if (!documentLoaded || !document || disposed) return;
    if (event.detail?.path && event.detail.path !== document.path) return;
    const item = event.detail?.item;
    if (!object(item)) return;
    const result = {};
    for (const key of ['uuid', 'reference', 'kind', 'name', 'pinNumber', 'pinName', 'ownerUuid', 'netName']) if (typeof item[key] === 'string' && item[key].length <= 500) result[key] = item[key];
    if (!result.uuid && typeof item.id === 'string' && item.id.length <= 200) result.uuid = item.id;
    if (!result.reference && typeof item.ref === 'string' && item.ref.length <= 100) result.reference = item.ref;
    send('objectSelected', { item: result, view: viewer.view });
  });
  listen(viewer, 'error', event => error(event.detail));
  for (const view of ['pcb', 'schematic', '3d', 'manufacturing']) listen(elements[`view-${view}`], 'click', safe(() => api.setView(view)));
  listen(elements.fit, 'click', safe(() => { viewer.fit(); drawOverlay(); }));
  listen(elements['layers-toggle'], 'click', () => { layersOpen = !layersOpen; updateLayers(); });
  for (const [id, value] of [['mode-pan','navigate'], ['mode-pin','pin'], ['mode-region','region']]) listen(elements[id], 'click', safe(() => setMode(value)));
  listen(elements.documents, 'change', () => {
    const id = elements.documents.value;
    if (document?.documents.some(item => item.id === id)) send('requestDocument', { id });
  });
  listen(viewer.stage, 'pointerdown', safe(event => {
    if (mode === 'navigate' || event.button !== 0) return;
    event.preventDefault(); event.stopImmediatePropagation();
    swallowClick = true;
    const rect = viewer.stage.getBoundingClientRect(); drag = { x:event.clientX-rect.left, y:event.clientY-rect.top, id:event.pointerId };
    viewer.stage.setPointerCapture?.(event.pointerId);
  }), true);
  listen(viewer.stage, 'pointerup', safe(event => {
    if (!drag || mode === 'navigate') return;
    event.preventDefault(); event.stopImmediatePropagation();
    const start = drag; drag = null;
    if (viewer.stage.hasPointerCapture?.(event.pointerId)) viewer.stage.releasePointerCapture(event.pointerId);
    const rect = viewer.stage.getBoundingClientRect(), a = screenToWorld(viewer,start.x,start.y), b = screenToWorld(viewer,event.clientX-rect.left,event.clientY-rect.top);
    let target = mode === 'region' ? { ...document.scope, kind:'region', area:{x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)} }
      : { ...document.scope, kind:'position', position:b };
    if(document.kind==='manufacturing')target={...document.scope,kind:'gerber',objectId:'gerber',context:{...document.artifact,...(target.area?{area:target.area}:{position:target.position})}};
    const checked = validateAnchor(target, document.scope);
    if (!api.authorized) throw new Error('Provider state changed; refresh before drafting.');
    send('draftAnchor', { anchor:checked }); mode='navigate'; updateModeControls();
    status('Local unpublished marker · write a comment, then Send message.');
  }), true);
  listen(viewer.stage, 'click', event => { if (swallowClick || mode !== 'navigate') { swallowClick=false; event.preventDefault(); event.stopImmediatePropagation(); } }, true);
  listen(viewer.stage, 'pointercancel', () => { drag=null; swallowClick=false; });

  const api = {
    authorized:false,
    get viewer() { return viewer; },
    async setDocument(payload) {
      if(disposed)return false;
      loadController?.abort();viewController?.abort();++viewGeneration;
      loadController=new AbortController();const signal=loadController.signal;documentLoaded=false;
      const ticket=++generation;let next;draft=null;
      try{next=validateDocument(payload);}catch(reason){document=null;markers=[];api.authorized=false;clearDrawing();error(reason);return false;}
      document = next; markers=[]; selected=null; mode='navigate'; api.authorized=false; clearTick(); overlay.replaceChildren(); updateDocuments();updateTabs();updateLayers();
      try {
        if(next.kind==='manufacturing' && typeof viewer.showManufacturing!=='function')throw new Error('This externally supplied KiView build does not support Gerber drawings. Update its viewer assets.');
        const loaded = await viewer.loadSource(next.source, {path:next.path,view:next.view,signal});
        if (disposed || ticket !== generation || !loaded) return false;
        documentLoaded=true;applyTheme();if(typeof viewer.getCamera!=='function')viewer.fit();installProjectionHooks(); send('documentReady', {view:viewer.view});
        status(`${next.path} · saved design · comments require a matching synced conversation`);
        return true;
      } catch (reason) { if (ticket === generation) { document=null; markers=[]; api.authorized=false; clearDrawing(); error(reason); } return false; }
    },
    setComments(payload) {
      const previousDraft=draft;draft=null;markers=[]; api.authorized=false;
      if (!documentLoaded) { updateModeControls();drawOverlay();return 0; }
      try {
        // The native host may connect a provider after an independent preview,
        // or authorize a new immutable review scope for identical saved bytes.
        // Identity-bearing host updates promote scope without reloading/losing
        // the user's camera; stale updates cannot rebind another document.
        if(document && payload?.status==='synced' && payload.path===document.path &&
            payload.source_sha256===document.source_sha256) document.scope=canonicalScope(payload.scope);
        if(document && ('path' in payload && payload.path!==document.path ||
            'source_sha256' in payload && payload.source_sha256!==document.source_sha256)) {
          updateModeControls();drawOverlay();return 0;
        }
        markers=validateComments(payload,document);
        api.authorized=Boolean(document?.scope && (document.kind!=='manufacturing'||document.artifact) && payload.status==='synced' && sameScope(payload.scope,document.scope));
        if (api.authorized && previousDraft) {
          try { draft=validateAnchor(previousDraft,document.scope); } catch { draft=null; }
        }
        selected=typeof payload.selected_id==='string'?payload.selected_id:null;
        updateModeControls();drawOverlay();
        return markers.length;
      } catch (reason) { updateModeControls();drawOverlay(); throw reason; }
    },
    setDraft(value) {
      draft=null;
      try {
        if (value == null) return true;
        if (!document?.scope || !api.authorized) throw new Error('Refresh the matching provider conversation before previewing a draft.');
        const checked=validateAnchor(value,document.scope);
        if (!checked.position && !checked.area && !checked.context?.position && !checked.context?.area) return false;
        if(checked.context && (!document.artifact || checked.context.file!==document.artifact.file || checked.context.sha256!==document.artifact.sha256))throw new TypeError('Draft belongs to another manufacturing artifact.');
        draft=checked;
        return true;
      } finally { drawOverlay(); }
    },
    async setView(view) {
      if (!['pcb','schematic','3d','manufacturing'].includes(view)) throw new TypeError('Unsupported drawing view.');
      if (!documentLoaded || !document || disposed) return false;
      viewController?.abort();++viewGeneration;
      if (view === 'schematic' && document.kind !== 'schematic' || view === 'pcb' && document.kind !== 'pcb' || view==='manufacturing' && document.kind!=='manufacturing') { send('requestView',{view}); return false; }
      if (view === '3d' && document.kind !== 'pcb') throw new Error('3D requires a saved PCB document.');
      if (viewer.view===view) return true;
      viewController=new AbortController();const ticket=generation,nav=viewGeneration;
      mode='navigate';clearTick();
      try {
        const result=await viewer.setView(view,{signal:viewController.signal});
        if(disposed || ticket!==generation || nav!==viewGeneration || !result)return false;
        applyTheme();installProjectionHooks();return true;
      } catch(reason) { if(disposed || ticket!==generation || nav!==viewGeneration)return false;throw reason; }
    },
    setTheme(value) {
      if (!['light', 'dark'].includes(value)) throw new TypeError('Theme must be light or dark.');
      if (disposed) return false;
      theme = value; applyTheme(); drawOverlay(); return true;
    },
    focusComment(identifier) {
      text(identifier,200);
      const marker=markers.find(item=>item.comment_id===identifier); if (!marker || !api.authorized) return false;
      selected=identifier;
      if (viewer.view==='3d') {
        if (marker.anchor.uuid && typeof viewer.selectObject==='function') viewer.selectObject(marker.anchor.uuid,{locate:true});
        else if (marker.anchor.uuid) viewer.renderer?.setSelection?.({uuids:[marker.anchor.uuid]});
        if (overlaysRegistered(viewer)) viewer.renderer?.setAnchor?.(marker.anchor);
      } else if (typeof viewer.setCamera==='function' && viewer.view!=='manufacturing') {
        const camera=camera2D(viewer);if(!camera)return false;
        let location={x:marker.x,y:marker.y};
        if (marker.anchor.uuid && viewer.selectObject?.(marker.anchor.uuid,{locate:false})) {
          const saved=viewer.getSelectionPosition?.();if(saved && [saved.x,saved.y].every(Number.isFinite)) location={x:saved.x,y:saved.y};
        }
        viewer.setCamera({...camera,center:location});
      } else { const camera=viewer.renderer?.viewport?.camera; if (typeof camera?.center?.set!=='function') return false; camera.center.set(marker.x,marker.y); viewer.renderer.draw(); }
      drawOverlay(); return true;
    },
    setMode,
    dispose() { disposed=true; ++generation; documentLoaded=false;loadController?.abort();viewController?.abort();++viewGeneration;api.authorized=false;markers=[];draft=null;document=null;clearTick(); stopHooks(); overlay.remove(); viewer.dispose(); },
  };
  applyTheme();updateTabs();updateLayers();
  return api;
}

export async function mountReviewBridge({ViewerClass,document:dom=globalThis.document,window:target=globalThis.window}={}) {
  let bridge;
  try {
    const KiCadViewer=ViewerClass||(await import('./vendor/review-viewer.mjs')).KiCadViewer;
    const ids=['viewer','status','layers','layers-toggle','documents','view-pcb','view-schematic','view-3d','fit','comment-menu','comment-label','mode-pan','mode-pin','mode-region'];
    const elements=Object.fromEntries(ids.map(id=>[id,dom.getElementById(id)]));
    elements.overlay=dom.getElementById('review-overlay');
    bridge=createReviewBridge({ViewerClass:KiCadViewer,elements,document:dom,postMessage:value=>nativePost(value,target)});
    // AddScriptMessageHandler('wayricadHost') owns a different global. Publish
    // our API before notifying Python, which may immediately send a document.
    target.wayricadReview=bridge;
    nativePost({type:'ready',protocol:1},target);
    return bridge;
  } catch(error) {
    bridge?.dispose();
    if(bridge&&target?.wayricadReview===bridge)delete target.wayricadReview;
    const status=dom?.getElementById('status');if(status)status.textContent=error.message;
    if(typeof target?.wayricadHost?.postMessage==='function')nativePost({type:'error',message:error.message},target);
    throw error;
  }
}
if (typeof window!=='undefined' && typeof document!=='undefined') {
  mountReviewBridge().catch(()=>{}); // Mount reports failures through the native channel and status.
}
