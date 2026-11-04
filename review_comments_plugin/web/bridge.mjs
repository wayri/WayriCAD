/* Read-only KiView integration. Host messages carry data, never executable code.
 * Projection adapter is pinned to owned-canvas Camera methods and board3d's
 * projectAnchor API. Do not replace unavailable mappings with guessed pixels.
 */
const NS = 'http://www.w3.org/2000/svg';
const LIMIT = 1e6;
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
  fields(value, ['repository', 'ref', 'file', 'provider', 'host', 'uuid', 'objectId', 'reference', 'netName', 'kind', 'variant', 'position', 'area']);
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
  return target;
}
export function validateDocument(value) {
  fields(value, ['source', 'path', 'source_sha256', 'scope', 'view', 'documents', 'current_document_id']);
  if (typeof value.source !== 'string' || value.source.length > 64 * 1024 * 1024) throw new TypeError('A bounded saved design source is required.');
  const path = text(value.path), kind = /\.kicad_pcb$/i.test(path) ? 'pcb' : /\.kicad_sch$/i.test(path) ? 'schematic' : null;
  if (!kind || !new RegExp('^\\s*\\(kicad_' + (kind === 'pcb' ? 'pcb' : 'sch') + '(?:\\s|\\))').test(value.source)) throw new TypeError('Source and saved design type do not match.');
  if (!/^[a-f0-9]{64}$/i.test(value.source_sha256)) throw new TypeError('A saved source SHA256 is required.');
  const scope = value.scope == null ? null : canonicalScope(value.scope);
  const view = value.view || kind;
  if (!['pcb', 'schematic', '3d'].includes(view) || kind === 'schematic' && view !== 'schematic' || kind === 'pcb' && view === 'schematic') throw new TypeError('View does not match this design type.');
  const documents = value.documents || [];
  if (!Array.isArray(documents) || documents.length > 128) throw new TypeError('Project document list is oversized.');
  const seen = new Set();
  const choices = documents.map(entry => {
    fields(entry, ['id', 'label', 'kind']);
    const id = text(entry.id), label = text(entry.label), type = entry.kind;
    if (seen.has(id) || !['pcb', 'schematic'].includes(type)) throw new TypeError('Invalid project document choice.');
    seen.add(id); return { id, label, kind: type };
  });
  const current = value.current_document_id == null ? null : text(value.current_document_id);
  if (current && !seen.has(current)) throw new TypeError('Current document is not in the host choices.');
  return { source: value.source, path, source_sha256: value.source_sha256.toLowerCase(), scope, view, kind, documents: choices, current_document_id: current };
}
export function validateComments(value, document) {
  fields(value, ['scope', 'status', 'markers', 'selected_id', 'path', 'source_sha256']);
  if (value.status !== 'synced' || !document?.scope || !sameScope(value.scope, document.scope)) return [];
  if (!Array.isArray(value.markers) || value.markers.length > 1000) throw new TypeError('Comment marker list is oversized.');
  return value.markers.map(item => {
    fields(item, ['comment_id', 'anchor', 'x', 'y', 'severity', 'state', 'label', 'region']);
    const anchor = validateAnchor(item.anchor, document.scope);
    const region = anchor.area ? [anchor.area.x, anchor.area.y, anchor.area.width, anchor.area.height] : null;
    if (item.region != null && (!Array.isArray(item.region) || item.region.length !== 4 || item.region.some((v, i) => number(v) !== region?.[i]))) throw new TypeError('Region does not match its anchor.');
    const position = anchor.position || (region ? { x: region[0]+region[2]/2, y: region[1]+region[3]/2 } : { x: number(item.x), y: number(item.y) });
    if (!anchor.position && !region && !anchor.uuid && !anchor.objectId) throw new TypeError('Comment has no saved location.');
    if (Math.abs(number(item.x)-position.x) > 1e-6 || Math.abs(number(item.y)-position.y) > 1e-6) throw new TypeError('Marker position differs from its anchor.');
    return { comment_id: text(item.comment_id, 200), anchor, ...position, region,
      severity: typeof item.severity === 'string' ? item.severity.slice(0, 40) : 'info',
      state: typeof item.state === 'string' ? item.state.slice(0, 40) : 'open',
      label: typeof item.label === 'string' ? item.label.slice(0, 160) : '' };
  });
}

/** Version-pinned adapter: use the renderer's own world camera, including flip. */
export function projectWorld(viewer, position, rect) {
  let projected;
  if (viewer.view === '3d') {
    projected = viewer.renderer?.projectAnchor?.({ position });
    if (!projected || projected.visible !== true) return null;
    projected = { x: projected.x-rect.left, y: projected.y-rect.top };
  } else projected = viewer.renderer?.viewport?.camera?.world_to_screen?.(position);
  return projected && [projected.x, projected.y].every(Number.isFinite) ? projected : null;
}
export function screenToWorld(viewer, x, y) {
  if (viewer.view === '3d') throw new Error('Point and region drafting require the PCB or schematic view; 3D has no verified screen-to-mm inverse.');
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
        button.disabled = value !== 'navigate' && (!api.authorized || viewer.view === '3d');
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
    clearTick(); stopHooks(); stopHooks=()=>{};
    viewer.pending?.abort(); if (Number.isFinite(viewer.generation)) ++viewer.generation;
    viewer.renderer?.dispose?.(); viewer.renderer=null;
    viewer.source=viewer.design=viewer.kind=viewer.view=null;
    viewer.stage.replaceChildren(overlay); overlay.replaceChildren();
    mode='navigate';drag=null;swallowClick=false;selected=null;draft=null;
    updateTabs();updateLayers();updateDocuments();
  }
  function updateTabs() {
    for (const view of ['pcb', 'schematic', '3d']) {
      const button = elements[`view-${view}`];
      if (button) { button.disabled = !document || view === '3d' && document.kind !== 'pcb'; button.setAttribute('aria-pressed', String(viewer.view === view)); }
    }
    updateModeControls();
  }
  function updateLayers() {
    if (!elements.layers) return;
    elements.layers.replaceChildren();
    const known = viewer.view === 'pcb' ? viewer.getLayers() : [];
    const toggle = elements['layers-toggle'];
    if (toggle) {
      toggle.disabled = !known.length;
      toggle.setAttribute('aria-expanded', String(layersOpen && Boolean(known.length)));
    }
    elements.layers.hidden = !layersOpen || !known.length;
    for (const layer of known) {
      const label = dom.createElement('label'), check = dom.createElement('input');
      check.type = 'checkbox'; check.value = layer; check.checked = viewer.renderer?.visibleLayers?.has(layer) ?? true;
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
    const rect = viewer.stage.getBoundingClientRect();
    overlay.setAttribute('viewBox', `0 0 ${Math.max(1, rect.width)} ${Math.max(1, rect.height)}`);
    for (const [index, marker] of markers.entries()) {
      const at = projectWorld(viewer, { x: marker.x, y: marker.y }, rect);
      if (!at) continue;
      const visible=at.x>=-20 && at.y>=-20 && at.x<=rect.width+20 && at.y<=rect.height+20;
      if (!visible && !marker.region) continue;
      const color = marker.comment_id === selected ? '#b36b00' : ['error', 'critical'].includes(marker.severity) ? '#b53434' : '#087f8c';
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
    if (draft && api.authorized) {
      const group = shape('g', {'data-draft':'true', 'aria-label':'Unpublished comment location'});
      const color = '#b36b00', area = draft.area;
      const center = area ? {x:area.x+area.width/2,y:area.y+area.height/2} : draft.position;
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
    if (viewer.view !== '3d') for (const key of ['draw', 'requestDraw', 'resize']) {
      if (typeof renderer?.[key] !== 'function') continue;
      const original = renderer[key];
      const replacement = function (...args) { const result = original.apply(this, args); drawOverlay(); return result; };
      renderer[key] = replacement; originals.push(() => { if (renderer[key] === replacement) renderer[key] = original; });
    }
    stopHooks = () => originals.forEach(restore => restore());
    drawOverlay(); updateLayers(); updateTabs();
  }
  listen(viewer, 'ready', () => { if (!disposed) installProjectionHooks(); });
  listen(viewer, 'select', event => {
    if (!document || disposed) return;
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
  for (const view of ['pcb', 'schematic', '3d']) listen(elements[`view-${view}`], 'click', safe(() => api.setView(view)));
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
    const target = mode === 'region' ? { ...document.scope, kind:'region', area:{x:Math.min(a.x,b.x),y:Math.min(a.y,b.y),width:Math.abs(a.x-b.x),height:Math.abs(a.y-b.y)} }
      : { ...document.scope, kind:'position', position:b };
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
      const ticket=++generation;let next;draft=null;
      try{next=validateDocument(payload);}catch(reason){document=null;markers=[];api.authorized=false;clearDrawing();error(reason);return false;}
      document = next; markers=[]; selected=null; mode='navigate'; api.authorized=false; clearTick(); overlay.replaceChildren(); updateDocuments();
      try {
        const loaded = await viewer.loadSource(next.source, {path:next.path,view:next.view});
        if (disposed || ticket !== generation || !loaded) return false;
        applyTheme(); viewer.fit(); installProjectionHooks(); send('documentReady', {view:viewer.view});
        status(`${next.path} · saved design · comments require a matching synced conversation`);
        return true;
      } catch (reason) { if (ticket === generation) { document=null; markers=[]; api.authorized=false; clearDrawing(); error(reason); } return false; }
    },
    setComments(payload) {
      const previousDraft=draft;draft=null;markers=[]; api.authorized=false;
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
        api.authorized=Boolean(document?.scope && payload.status==='synced' && sameScope(payload.scope,document.scope));
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
        if (!checked.position && !checked.area) return false;
        draft=checked;
        return true;
      } finally { drawOverlay(); }
    },
    async setView(view) {
      if (!document) return false;
      if (view === 'schematic' && document.kind !== 'schematic' || view === 'pcb' && document.kind !== 'pcb') { send('requestView',{view}); return false; }
      if (view === '3d' && document.kind !== 'pcb') throw new Error('3D requires a saved PCB document.');
      mode='navigate'; clearTick(); const result=await viewer.setView(view); if (result) { applyTheme(); viewer.fit(); installProjectionHooks(); } return result;
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
      if (viewer.view==='3d') { if (marker.anchor.uuid) viewer.renderer?.setSelection?.({uuids:[marker.anchor.uuid]}); viewer.renderer?.setAnchor?.(marker.anchor); }
      else { const camera=viewer.renderer?.viewport?.camera; if (typeof camera?.center?.set!=='function') return false; camera.center.set(marker.x,marker.y); viewer.renderer.draw(); }
      drawOverlay(); return true;
    },
    setMode,
    dispose() { disposed=true; ++generation; api.authorized=false;markers=[];draft=null;document=null;clearTick(); stopHooks(); overlay.remove(); viewer.dispose(); },
  };
  applyTheme();updateTabs();updateLayers();
  return api;
}

export async function mountReviewBridge({ViewerClass,document:dom=globalThis.document,window:target=globalThis.window}={}) {
  let bridge;
  try {
    const KiCadViewer=ViewerClass||(await import('./vendor/web-library/kicad-viewer.mjs')).KiCadViewer;
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
