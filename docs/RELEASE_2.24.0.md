# KiWay v2.24.0 Release Notes

## Harness and Cable Workbench 0.4.0

- Joins audited board-internal controller maps through arbitrary harness pin
  mappings to produce complete IC-to-IC and IC-to-peripheral paths.
- Preserves ordered net segments, connector pins, series passives, explicit
  active-device transitions, conditions, confidence, and ambiguity state.
- Adds source and destination reference wildcards and connector-only incomplete
  rows without allowing filters to reintroduce excluded endpoints.
- Adds a self-contained interactive HTML harness with pan, zoom, draggable
  nodes, clickable path details, bundle/status/search filters, sortable tables,
  findings, construction data, and a procurement BoM.
- Adds non-corresponding, alphanumeric, and one-to-many mappings through the
  tabular pin editor and CSV round trips.

## Automation and CLI

- Adds `kiway capabilities`, one-shot `kiway run`, and NDJSON JSON-RPC 2.0
  `kiway serve --stdio` control for external workflow engines.
- Extends `harness.build` with path documents, endpoint wildcards, partial-path
  policy, and optional standalone HTML output.
- Documents deterministic use from CI, jobsets, and Doki-style controllers.

## Safety

The harness tool does not infer conduction through active devices. MOSFET, BJT,
jumper, and other IC crossings require an explicit Pin Extractor traversal rule,
and conditional/ambiguous status is retained through every export. Harness
correspondence is not proof of electrical, mechanical, or regulatory fitness.
