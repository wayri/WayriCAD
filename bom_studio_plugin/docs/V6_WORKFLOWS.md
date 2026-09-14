# WayriCAD BOM Studio 0.6 — Local engineering library and controlled reuse

This guide describes implemented workflows, not a claim that all engineering decisions have been automated. Developer preview, 9 September 2026. Use disposable project copies for initial acceptance.

## 1. A persistent catalog separate from projects

Choose **Library & control → New library** and an absolute, new/empty directory on a local disk. Type CREATE. The default checkbox remembers this directory on the current computer; uncheck it for a disposable catalog. **Attach library** reuses an existing compatible catalog. A project-specific attached path takes precedence over the computer default. Saving the workspace retains that project-specific path.

The local SQLite database holds exact orderable identities, internal part numbers, fields/tags/notes, captured assets, project provenance, lifecycle/package/supplier evidence, inventory lots and review records. Full-text search uses SQLite FTS5 where supported, with a bounded fallback otherwise. Internal part numbers are unique inside a catalog. Full MPN case, punctuation and orderable suffixes are preserved; manufacturer whitespace/case is normalized, but corporate aliases are not guessed. Parts without both manufacturer and MPN remain generic observations and cannot be pooled as orderable stock.

A part has separate **preference** (candidate/preferred/deprecated/blocked), dated **lifecycle**, **stock evidence**, and **review/qualification** state. Preferred does not mean qualified. Green observation labels are not purchasing guarantees. Unknowns have their own labels; every color state has text and a tooltip.

**New part / Edit** opens a GUI with common fields plus arbitrary string-property JSON, tags, notes and optional source-linked land-pattern/candidate-alternate definitions. Preview → CATALOG records an immutable revision and an actor/reason. Identity cannot be renamed in place. To correct a genuinely different manufacturer/MPN, make a different identity rather than rewriting its history. Conflict indexes must be resolved deliberately. These catalog edits are immediate and independent of project Save/Undo.

**Inspect** includes complete revision and provenance data. Search covers MPN, value, footprint, internal number, tags, custom properties, source-project/reference/variant strings and recorded supplier/lifecycle metadata. The catalog search is text search, not the typed BOM threshold language. Use project thresholds for numeric property predicates after applying/selecting parts.

## 2. Harvest selected projects

Choose **Harvest projects…**, enter absolute project paths or directories one per line, then optionally include subdirectories, every variant and captured assets. Scanning is read-only and cancelable. It reads saved sources and saved workspaces, not unsaved KiCad/browser memory. Directory discovery targets `.kicad_pro`; explicit root `.kicad_sch` files also work. No full-disk search, network request, cloud upload or automatic distributor scraping occurs.

The returned plan includes project failures, part observations, source/sidecar/asset hashes, original raw fields, resolved metadata, references/instances and variant membership. Review/download the full plan, provide an actor and type IMPORT. Nothing is imported merely because scanning finishes. Changes to bound source files invalidate import. Successful projects can be imported despite failed projects only after the explicit partial-import acknowledgement; the report retains failures. Cancellation discards the read result, with no catalog mutation.

Exact identities are deduplicated; harvested observations from another project do not silently overwrite curated nonblank values. Different values become conflict records with provenance. Conflicting critical ratings or geometry must be resolved before a positive reuse screen. Reimporting the same unchanged plan is idempotent for identical observations. Harvesting retains distinctions between a source observation and an engineering-approved component.

### Captured assets and native KiCad libraries

Where supported, harvesting captures the project's embedded symbol definition and resolved local `.kicad_mod` bytes. Duplicate assets use content hashes. Inherited/external unresolved symbols and ambiguous assets are not guessed or flattened. A footprint root can be configured in the existing **BOM health → Health settings** directory list.

Select catalog identities and choose **Export selected native library**. The ZIP contains a `.kicad_sym`, a `.pretty` directory when captured footprints are available, a mapping/manifest and warnings. Catalog metadata/internal numbers are included as symbol properties. It does not edit source projects or installed library tables. Install the extracted files in KiCad's library manager yourself and validate them on a disposable project. Native KiCad loading has not been executed here.

Unambiguous usable symbols are required; rejected/missing assets appear in warnings. A part without a captured footprint may retain its original footprint link, so it is not necessarily a self-contained library. 3D model links are deliberately omitted from captured footprint exports rather than claiming that unbundled files are embedded. A variable expression is not flattened into a new independent library field automatically. Rights to harvested proprietary or third-party assets remain your responsibility.

Metadata JSON export intentionally excludes review-account secrets and binary asset bodies. It is a searchable data snapshot, not a one-click full backup/restore format. Close the app and back up the whole catalog directory for recovery; do not store a live SQLite/WAL database in a cloud-sync or multiuser shared folder.

## 3. Recommend parts in a new project

After attaching the reusable catalog, open a saved project and use **Recommend & reuse → Choose component…**, the row's ◇ action, or **Recommend selected part** with exactly one checked component. An ordinary row click also produces a nonintrusive candidate cue when a catalog is attached. It does not place/edit anything automatically.

Candidates first match the exact selected footprint and normalized supported resistor/capacitor/inductor value notation. `4k7` and `4700` can match; active-device labels are not interpreted as electrical specifications. Results show match reasons, rank, missing constraints, preference, catalog conflicts and dated health. The numeric rank is a deterministic ordering hint, not a probability of compatibility.

Different supplied tolerance/voltage/power/dielectric/current/temperature/qualification fields block a favorable screen. Missing passive essentials remain explicitly missing—even when both records are blank. Equal strings are only equal recorded metadata; no derating, pin-swap, input/output electrical or radiation-qualification inference is made. Historical NRND/EOL and blocked/conflicting catalog records prevent ordinary recommendation application.

Choose **Review use…**. The plan identifies the exact catalog revision and component edits. Acknowledge engineering review and any raw-expression loss, then type EDIT. By default it fills manufacturer, exact MPN, relevant datasheet and catalog/internal IDs; it preserves the component Value and footprint. Additional CLI field selections remain subject to the same safe edit mechanism. This is property editing of existing symbols, not symbol replacement/placement, pin reconnection or footprint geometry editing. Save workspace separately; use native APPLY only after a fresh native diff and closed editors.

## 4. Catalog health without API keys

Use **Catalog health** to assess the full matching catalog. Configure text scope, market, observation freshness (hours), and a low-stock warning quantity. The scan is local, read-only, reports progress and can be canceled. The screen limits the summary table to 200 identities; full JSON contains all assessed identities and counts. CLI has explicit pagination or `--all`.

Evidence is entered from a reviewed exact part/source or imported via supported catalog evidence JSON. The older project-level DigiKey/Mouser CSV/XLSX/capture workflows are retained, and harvesting incorporates their matching evidence. There is **no new unattended authenticated supplier connection or live lifecycle feed**. No keys or money are needed by the local engine, but stale cached data does not become current data.

Stock must be numeric, dated, reviewed, sourced and for the selected market to be eligible. Unknown/missing/future/stale observations do not become zero or sufficient availability. Low stock means that the largest single eligible observed offer is below the configured warning quantity; offers are not summed. Catalog health screens coverage of one part/order minimum, not your complete build demand. Use multi-build planning for required quantities.

Negative historical lifecycle labels such as NRND, EOL, Obsolete and Discontinued remain warnings even after the observation becomes old. A later positive label does not automatically erase them. This is conservative conflict visibility, not an authenticated PCN decision. Correct source evidence and record the engineering rationale before reuse. Observed stock is not reserved, verified purchasable or guaranteed independent across listings.

## 5. Declared land-pattern and pin-function comparison

Choose **Land patterns & pins → Compare geometry & pins…**, select the component, and supply `wayricad-land-pattern-1` JSON. A schema example is included, explicitly synthetic and not production geometry. Store a verified specification on the relevant catalog revision for repeated controlled reviews.

Use a manufacturer **recommended land pattern**, not just a body/package outline. Record exact manufacturer/MPN, source URL, document revision, document SHA-256, page/locator and transcriber/reviewer. Enter coordinates in the same top-view millimeter origin/orientation as the selected footprint. No rotation/mirroring alignment is inferred. A declared document hash is an assertion until you verify the actual source bytes; the tool does not download/authenticate the drawing.

Checks cover every numbered electrical pad instance, its center, size, rotation, supported shape, mounting kind, layer set, drill and explicitly recorded mask/paste/roundrect values. Duplicate pad numbers are not collapsed into one geometry instance. Pin-function maps require explicit accepted names for all actual symbol pins; no fuzzy pin-function or pin-swap equivalence is inferred. Angular and dimensional tolerances are explicitly entered.

Statuses are **MATCHED_DECLARED_CHECKS**, **INCOMPLETE** or **MISMATCH**. Missing implicit mask/paste defaults, unresolved symbol pins, custom pad geometry/drill offsets or incomplete exposed-pad coverage do not pass. Unsupported shapes remain unsupported. Courtyard, blank paste apertures, solder-joint manufacturability, electrical pin types, current/creepage/thermal/radiation behavior and assembly-process qualification are outside this comparator.

A matched report includes source, specification, symbol and footprint hashes. It is not approval. Controlled review can require a named engineering decision bound to that exact matched report.

## 6. Controlled approvals, scoped alternatives and waivers

Create a local administrator, then separate engineering/supply reviewers. Passphrases are salted and PBKDF2-hashed. Admin role manages accounts and revocations; it is not silently allowed to issue engineering/supply decisions. Names cannot be reassigned to a new person. There is no starter account/password. Deactivation is available through the CLI/API. See CONTROL_TRUST.md for the trust boundary.

Configure review policy: required engineering/supply roles, BOM error or warning threshold, exact catalog membership, dated stock observations, and declared qualification requirements. **Assess current approval state** produces an input fingerprint and findings. Record each decision with reviewer authentication, reason, evidence/change-control reference, expiry timestamp, exact target and REVIEW confirmation.

A warning/unknown waiver targets exactly one current finding and the appropriate role; it does not suppress all future instances of that rule. Errors cannot be waived. Qualification approval must name a freshly computed fully matched report. Required release approvals cannot be recorded until relevant findings/qualifications are resolved. Revoking an earlier decision requires the local admin role and exact decision ID. Expiry, revoked/inactive accounts, mismatched HMAC or input drift prevent a decision from counting.

Catalog **alternate links** are revision-pinned candidate relationships with explicit scope, evidence and reason. The assessment derives a target hash for links of parts used by the current assembly. A local engineer can issue an `alternate` decision for a current unblocked link, supplying qualification evidence. Conflicting values/footprints/recorded constraints, risk state or changed linked revisions block that approval. It is a human scoped engineering decision, not proof of complete automatic electrical interchangeability. It does not replace any part or create a universal global approved-alternate flag. An unchanged primary assembly does not need every unused candidate alternate approved to be released.

Fingerprints bind source files, substantive workspace state, active variant, catalog epoch/revisions, current geometry availability/hash, policy and relevant findings/qualification/alternate targets. New evidence, inventory/catalog changes, changed project fields or geometry, and freshness changes that alter findings require reassessment. Catalog epoch binding is deliberately conservative: even an unrelated catalog edit can stale an approval. View/column rearrangement and activity-history-only changes do not invalidate engineering context. Moving paths may invalidate it. Source hashes cannot detect unsaved KiCad editor memory.

**Export controlled pipeline config** creates a normal release/job-set config with an optional `release_control` gate. Existing pipelines without this key keep earlier behavior. The gate rechecks current authenticated context before ordinary BOM outputs; a missing/stale decision produces a FAILED manifest and diagnostics, not normal BOM exports. The approval is of the engineering context/policy, not a digital signature of every eventual output byte or arbitrary export-format choice.

## 7. Independent BOM variants

Create a BOM-only variant in **BOM-only variants**, choose parent and mode, preview, and type VARIANT. **Derived** inherits parent changes until overridden. **Pinned** copies current raw properties, flags and effective variable definitions into its overrides. Expressions remain expressions; they are not silently evaluated into constants. Tags and description are independent metadata.

Manage rename, reparent, tags/description, lock/unlock and removal through reviewed operations. Cycles, conflicting names and removing parents with children are rejected. A child created through the older variant interface inherits BOM-only status from its BOM-only parent. Native-syncable variants cannot inherit from a BOM-only parent.

BOM-only variants participate in project BOM editing, compare/export, analytics and pipelines, but are **always omitted from native KiCad variant writes**. Their variables and overrides survive a supported native synchronization of other data. Default/native variants retain their original behavior. The active variant selector labels BOM-only and locked states.

Locks guard direct editing and variable changes. A locked derived variant can still receive intentional changes from its parent; it is not a frozen archive or authorization mechanism. Project-wide schema enforcement is refused while a BOM-only variant is locked, avoiding hidden schema changes. Pinned copies cannot freeze changing circuit topology, geometry, built-ins or external sheet context. Use released source/snapshots plus a fresh review when those matter.

## 8. Multi-build purchasing and inventory scenarios

Choose **Multi-build planning → Configure builds & offers…**. Add rows for build ID, saved project (blank = current workspace), variant, board count, numeric priority, optional due date and attrition. Lower priority numbers are processed first, then due date and build ID. DNP/DNI/BOM-excluded parts do not create purchasing demand. Different builds of different variants are intentionally added; one variant's alternative assemblies are not automatically all ordered.

**Inventory lots…** accepts a reviewed JSON array of lot ID, exact catalog identity, quantity, reserved quantity, location, expiry, status, observation source/time and notes. Inventory apply is an upsert: omitted lots are retained. Use zero quantity or scrapped status to retire a lot. Quarantined, expired, stale or unusable observations do not supply the plan. Review and type INVENTORY. Allocation never mutates quantities or reservations.

Offers specify exact catalog part ID, supplier/SKU, inventory-pool ID, numeric available quantity, market, observation time, source URL, review acknowledgement, typed lead days, currency/unit price, MOQ, multiple and optional entered quantity-price tiers. **Prepare offers from catalog evidence** copies matching observations into the session form; missing numeric lead times/prices still need review. A prose lead-time label is not guessed as days. With a due date, unknown lead time cannot prove on-time supply.

The planner deduplicates pool usage and consumes each observed pool once across builds. It rejects conflicting identities and recorded risks, uses lot stock after reservations, then eligible entered supplier offers. Pack/MOQ surplus can satisfy later builds without a duplicate purchase if its arrival fits. Final order allocated/overbuy quantities account for that later reuse. Same-MPN but conflicting recorded value/footprint descriptions do not silently combine.

Split sourcing is off until both **Allow reviewed split orders** and **independent-pool acknowledgement** are selected. Pool IDs are user assertions; this tool cannot prove that two distributor listings are independent inventory. Supplier priority comes before numeric price ordering. Different currencies remain separate; deterministic currency-code ordering is disclosed rather than called a cross-currency optimum. Quantity tiers are supplied by you, not fetched live.

Reports include every demand line, allocation, planned order, remaining stock/surplus, shortfall, known cost by currency, source hashes and per-build workspace fingerprints. UI configuration is session-local; save/export the complete JSON config to rerun it in CLI. The plan is not globally optimized MRP, an ERP connector, a reservation transaction or purchase authorization. Taxes/freight/labour, inventory carrying cost and uncertain future deliveries are not modeled.

## 9. Source-linked mass suggestions

**Mass suggestions → Find missing-mass suggestions…** considers blank values only. A deliberately entered zero or a nonblank `unknown` is not replaced. Exact catalog observations come first. Source-linked typical resistor, MLCC and selected small-semiconductor package proxies are offered only for their supported patterns; unsupported packages remain unknown.

For MLCCs the options retain differing thickness/dielectric constructions. For active devices a representative manufacturer's exact package/part mass is a proxy, not a promise for every device sharing that package. These estimates are not computed from footprint pad area. Some resistor proxies come from a clearly marked historical EOL series: they are mass examples, never recommended current purchasable parts.

Select a source per component, inspect assumptions and uncertainty text, preview, acknowledge estimates, and type EDIT. Acceptance adds the mapped mass plus **Mass_Basis, Mass_Source, Mass_Assumptions and Mass_Uncertainty**. The analytics engine flags accepted estimated mass so a complete numeric subtotal is not misrepresented as measured assembly mass. No numeric error bar is fabricated where the manufacturer has not supplied one. Exact catalog assertions are still only as trustworthy as their entered source.

## 10. Performance, accessibility and acceptance

Catalog paging is indexed in SQLite. Harvest and full health scans are bounded/cancelable read tasks. The optional **Bounded viewport** in the ungrouped BOM renders at most 45 data rows while supporting scrolling, selected rows, threshold/live highlights and keyboard navigation. Control-Home/End jumps to first/last component; arrow and Page keys move within the window. Pending inline editing is protected from scroll replacement.

This is **DOM windowing**, not a streaming project parser: the current workspace still resolves/holds all component rows. Group pages retain existing pagination; expanding a very large group is not virtualized. Full report JSON and native project parsing can still consume significant memory. No million-component performance claim is made.

Color labels have text/tooltips, dialog labels and focus outlines are supplied, engineering tabs support arrow navigation, total virtual row counts/indexes are exposed, and reduced-motion preferences are respected. Actual assistive screen-reader and comprehensive WCAG acceptance were not executed. The measured benchmark describes the exact tested environment; it is not a universal performance promise.

The host runner never substitutes a fake driver for KiCad. Without an installed executable it records UNAVAILABLE/SKIPPED and returns 6. Manual cross-selection/viewport/native-library/OS checks remain NOT_EXECUTED until genuinely performed on each host. See HOST_ACCEPTANCE.md and TEST_REPORT.md.
