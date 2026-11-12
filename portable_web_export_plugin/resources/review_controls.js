/* Host-only helpers: saved identities are authoritative; labels remain inert. */
globalThis.WayriCADPortableReview = (() => {
  const unique = matches => matches.length === 1 ? matches[0] : null;
  const idsFor = component => [component.boardUuid, ...(component.schematicUuids || [])].filter(Boolean);
  function findPart(component, parts) {
    const ids = idsFor(component);
    if (ids.length) return unique(parts.filter(part => ids.includes(part.uuid) || ids.includes(part.schematicUuid)));
    return unique(parts.filter(part => !part.uuid && !part.schematicUuid && part.reference === component.reference));
  }
  function componentForItem(item, components) {
    if (!item || item.type === 'net' || item.kind === 'net') return null;
    const ids = [item.ownerUuid, item.parent?.uuid, item.uuid, item.id].filter(Boolean);
    if (ids.length) return unique(components.filter(component => idsFor(component).some(id => ids.includes(id))));
    return unique(components.filter(component => !idsFor(component).length && component.reference === (item.reference || item.ref)));
  }
  function exactMatch(items, query, identityKeys, labelKey) {
    const identities = items.filter(item => identityKeys.some(key => item[key] && item[key] === query));
    const matches = identities.length ? identities : items.filter(item => item[labelKey] === query);
    return {item: unique(matches), count: matches.length};
  }
  function showSelection(node, values) {
    node.replaceChildren();
    for (const value of values) {
      const line = node.ownerDocument.createElement('div');
      line.textContent = String(value ?? '');
      node.append(line);
    }
  }
  function trackingRecord(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('Invalid tracking row.');
    const quantity = name => {
      const result = value[name] ?? 0;
      if (!Number.isSafeInteger(result) || result < 0 || result > 1e9) throw Error('Invalid tracking quantity.');
      return result;
    };
    const assembly = value.assembly ?? 'not-started';
    if (!['not-started','in-progress','complete','blocked'].includes(assembly)) throw Error('Invalid assembly state.');
    if (value.dnp !== undefined && typeof value.dnp !== 'boolean') throw Error('Invalid DNP state.');
    if (value.notes !== undefined && (typeof value.notes !== 'string' || value.notes.length > 8192)) throw Error('Invalid notes.');
    return {orderedQty: quantity('orderedQty'), receivedQty: quantity('receivedQty'), assembly,
            dnp: value.dnp ?? false, notes: value.notes ?? ''};
  }
  function trackingRows(rows, components) {
    if (!rows || typeof rows !== 'object' || Array.isArray(rows)) throw Error('Invalid tracking rows.');
    const known = new Set(components.map(component => component.id)), result = Object.create(null);
    for (const [id, value] of Object.entries(rows)) if (known.has(id)) result[id] = trackingRecord(value);
    return result;
  }
  return Object.freeze({findPart, componentForItem, exactMatch, showSelection, trackingRows});
})();
