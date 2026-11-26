# Local Ollama Assistant integration

This audit records the historical 4.8.9 model integration. See the [current Assistant workflow](../../suite_assistant_plugin/README.md) for the local fuzzy planner.

Source validation date: 2026-11-20. This is a source feature, not a claim that
published 4.8.8 binaries contain it.

## Boundary

`wayricad_runtime/assistant_ollama.py` calls the local Ollama chat API using
standard-library HTTP, pinned loopback addresses, no proxies and no redirects.
It probes text-completion/context capability and disables thinking only when
advertised. No installation, model pull, shell generation or provider fallback
is implemented. An unavailable service leaves deterministic Local commands usable.

All 62 registry actions (27 tools including the Assistant catalogue) are exposed.
Relevant field schemas are retrieved for a compact prompt; every action ID
remains available. Actions outside that field shortlist require host clarification.
Strict host validation rejects unregistered actions, model-supplied paths,
unknown switches, invalid numbers and malformed/duplicate-key JSON. Null input
is unknown, not zero. The flat wire schema avoids a grammar failure observed
with large object unions/string repetition limits in the installed Ollama engine.
Host size/type validation remains authoritative.

Plans use the existing source hashes, sealed-plan validation and typed argument
adapters. LLM plans never auto-run in the GUI. Proposed values are editable;
clearing an optional field omits it, and unwanted tasks can be removed. Editing
an input disables Run until the reviewed values are resubmitted. Cached proposals
are bound to query, saved context, endpoint and model. No design Apply is exposed.

Explanations are separate inert model text. The host retains statuses and hashes
bounded numerical JSON before and after inference. The response must reference
existing evidence IDs; it cannot update numerical results. Valid citations and
JSON are not proof that the prose is scientifically correct.

## Checks performed

- Python 3.14 source tests: Assistant engine, adapters, source freshness and
  Ollama integration: 57 tests and 338 subtests, including registry-wide
  proposal/adapter contracts.
- KiCad 10 native Python/wx tests: 25 window tests, including the LLM explicit
  Run gate, provider/model invalidation, input correction, task removal,
  failed-run isolation and closed-window callbacks.
- Real loopback HTTP tests: inventory, redirects, size limits, timeout,
  cancellation and a connection-closing response with a stalled body.
- Documentation source validation and whitespace checks.

No every-plugin scientific/native workflow or installed IPC-toolbar session was
qualified by these checks. Existing adapters still have their own dependencies,
input requirements and numerical limits. No hosted CI result is claimed here.

## Live local model trial

An existing `qwen3.5:4b` model ran on CPU; no model was downloaded. Natural-language
microstrip planning was **not exact**: an attempt added an unrequested copper
thickness and a help task. The exact-input acceptance helper stopped before
execution. These are real observed errors, not accepted engineering assumptions.

An explicit fixed-fixture review removed those changes and passed the intended
microstrip geometry to the existing deterministic RLC adapter. The actual tool
completed and wrote numerical JSON. Local Ollama then returned an explanation
with evidence ID E1, preserved host status `completed`, and repeated the original
geometry/dielectric/reference-conductor limitations. The first summary was generic;
removing the execution counter from the evidence prompt produced a qualitative
cross-section/model-scope explanation. It still did not discuss the impedance
value, so this trial does not establish numerical reasoning or planning accuracy.

Evidence report SHA-256:
`5b88153c028e683f4a2c4e19234b4569698ef41a215f205e077696764674fad2`.
Explanation response SHA-256:
`015d49513fe943f9b72e3a04e4557ca6c5a644911a3a1cc933a76b5320858ac6`.

Use `tools/verify_assistant_ollama.py` for the opt-in exact-input trial. A saved
proposal can be exercised with its explicit `--review-proposal` fixture mode;
that mode reports whether the original proposal was exact and must not be
presented as autonomous success. The CLI `explain` command can separately inspect
an existing run without rerunning the scientific tool.

## Remaining limits

- User-managed Ollama service/model setup; CPU latency depends on the machine.
- Only loopback HTTP, text proposals and numerical JSON evidence; no cloud,
  voice or vision ingestion.
- Registered adapters, not every GUI feature or autonomous board modification.
- 96 KiB interpretation evidence and bounded request/response budgets; large
  studies are rejected rather than truncated. The stricter context ceiling
  charges serialized request bytes, complete template/system bytes and output
  headroom against 16,384–32,768 tokens within advertised model capacity.
- LLM suggestions require engineering review, convergence checks and applicable
  native validation. No LLM response grants manufacturing or safety approval.
