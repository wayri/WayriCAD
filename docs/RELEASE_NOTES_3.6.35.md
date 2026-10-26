# WayriCAD 3.6.35

Quick PI and Quick SI now make return setup easier to find and complete.

- **PI return review:** starts from the Setup net. Choose its return net, or
  explicitly confirm a ground-name suggestion, then review. Multiple returns,
  optional pads, sampling and detailed evidence stay collapsed.
- **PI DC ground drop:** open **Rails / ground returns…**. The default rail and
  return tables replace the JSON-first view. One form shows supply ground and
  every load-ground pad unit, with searchable multi-pad pickers, optional
  footprint-based suggestions and add/edit/remove actions. Existing independent
  return models and advanced settings are preserved.
- **SI:** one visible optional return selector, with advanced nets/pins/reference
  settings collapsed. Return pins from the selected endpoint's footprint appear
  first. A common return setup can be applied to study cases explicitly.
- Changed inputs clear stale results and endpoint mappings. Long names remain
  searchable and duplicate pad labels retain exact identities. Updated help,
  guides and native screenshots accompany the workflows.

These are workflow changes. Name and footprint suggestions require review;
they do not infer a closed current loop. PI geometric coverage, DC return
conduction and SI reference-layer assumptions remain distinct models.

See the [release validation](audits/RELEASE_3.6.35.md).
