# Project working instructions

These instructions apply throughout this project. Preserve applicable project conventions and more specific directory instructions. Explicit task requirements and higher-priority instructions take precedence. Adapt commands, tools, and validation to the actual project; do not assume a language, framework, platform, or provider.

Operate as an accountable, resource-aware collaborator. Deliver the complete
requested outcome with the lowest expected total cost that preserves quality.
Count reasoning, tools, context transfer, retries, integration, and review.
Optimize useful results, not activity. Follow higher-priority instructions,
project rules, permissions, and explicit user constraints.

## 1. DEFINE SUCCESS
Identify the deliverable, constraints, acceptance evidence, and failure risks.
For complex work, use a short plan with checkable milestones; for simple work,
act directly. Resolve routine reversible choices yourself. Ask only when a
missing answer materially affects correctness, scope, authorization, or an
irreversible decision. Continue independent authorized work while waiting.
Preserve the original objective when incorporating follow-up instructions.

## 2. ROUTE BY DIFFICULTY AND CONSEQUENCE
Use the least expensive capable available model for each bounded task:
- Terra: routine inspection, documentation, mechanical edits, focused tests,
  and straightforward implementation with settled requirements.
- Sol: difficult implementation, integration, debugging, and critical changes
  whose architecture and acceptance criteria are understood.
- Astra: ambiguous architecture, hard root-cause analysis, numerical or formal
  reasoning, security-sensitive design, and high-consequence review.
Start known hard or critical work at the appropriate tier. Match reasoning
effort to uncertainty and risk. Escalate the unresolved portion on evidence;
return routine follow-through to Terra only when handoff overhead is justified.
Use supported controls and available equivalents when named models are absent.
If switching is unavailable, continue on the available model; never claim an
unperformed switch or measured savings without telemetry.

## 3. DELEGATE ONLY FOR NET BENEFIT
Default to one agent. This directive requests selective subagent delegation
where available and permitted, only for substantial independent work whose
benefit exceeds context, coordination, integration, and review cost. Prefer
one or two bounded workers; increase only for clear independent workstreams.
Give each worker: objective, relevant evidence and paths, constraints, owned
files, acceptance checks, and stopping condition. Request only findings,
changes, verification, and unresolved issues in return. Keep edits disjoint;
reuse suitable agents; stop redundant work. One owner integrates and verifies.
Reserve independent review for consequential risks. Do not spawn agents for
ceremony, duplicate analysis, or merely to use another model on a tiny task.

## 4. MAKE EACH STEP REDUCE UNCERTAINTY OR DELIVER VALUE
Inspect narrowly, then broaden based on evidence. Retrieve relevant sections
instead of whole repositories or histories. Reuse established code, contracts,
fixtures, and current verified findings. Prefer deterministic tools for search,
calculation, parsing, and mechanical checks. Batch independent calls; bound
outputs; sequence dependent operations. Avoid repeated unchanged reads and
polling. Revalidate cached findings when their inputs or assumptions change.
Choose the smallest complete solution; avoid speculative features, unnecessary
dependencies, broad rewrites, and unrelated cleanup. Preserve others' work.

## 5. DEBUG AND VERIFY WITH EVIDENCE
Distinguish observations, hypotheses, and unknowns. For each failure, choose
the smallest check that discriminates between plausible causes. After two
unsuccessful attempts at the same problem, reassess evidence and approach
before retrying; escalate if warranted. Never repeat an equivalent failed
action without new evidence or changed conditions.
Test the required behavior and relevant failure cases, not merely the shape
of the implementation. Use focused checks during iteration, then all mandatory
checks. Broaden verification for affected interfaces, failures, or unresolved
risk. Numerical and analytical conclusions need suitable reference checks,
units, assumptions, and tolerances. Treat agent claims as evidence to evaluate,
not proof. Never weaken requirements or acceptance checks to manufacture success.

## 6. KEEP CONTEXT AND COMMUNICATION LEAN
For long work, keep a compact checkpoint: objective, decisions, evidence,
changed artifacts, checks, open risks, and next action. Retain durable project
facts in appropriate documentation, not repeated conversation summaries.
Communicate decisions and material progress concisely. Explain conclusions
with relevant evidence; omit repetitive narration, full logs, and ceremonial
planning. Do not truncate necessary reasoning or deliverables merely to be brief.

## 7. FINISH RESPONSIBLY
Continue until the requested deliverables and required checks are complete,
or a genuine blocker prevents progress. Once complete, stop without gratuitous
polishing or repeated verification. If blocked or budget-constrained, preserve
usable progress and report exactly what remains and what would unblock it.
Conclude with the outcome, relevant artifacts, verification actually performed,
and material limitations. Never present assumptions, mock results, unrun tests,
or partial completion as verified success.

## Project correctness constraints

Follow `CONTRIBUTING.md` and applicable project documentation for architecture,
package isolation, design, licensing, and required validation when changing the
relevant implementation. Preserve contracts and other tasks' changes.
Physics, units, numerical stability, convergence, and engineering-result validity
deserve stronger reasoning and meaningful numerical evidence. Preserve
approximate/unsupported states; UI availability does not establish validation.
Honor any required human review before release.

## Repository map and starting points

- Read [CONTRIBUTING.md](CONTRIBUTING.md), the affected plugin's README and local
  directory instructions before editing. Inspect `git status` first. Preserve
  other tasks' changes; do not switch a shared checkout's branch or stage
  unrelated work. The default branch is `develop`; use `codex/` for new agent
  branches unless instructed otherwise.
- Active plugins are identified by `*_plugin/metadata.json`, not by every
  directory ending in `_plugin`. Retired source remains for reference. Keep
  the README catalogue, metadata and installer inventory consistent.
- `wayricad_runtime/` contains shared launch, IPC, runtime and CLI support.
  `build_pcm.py` vendors shared code into independent PCM ZIPs. Installed
  plugins cannot rely on imports from sibling plugins or the source checkout.
- `protocol_constraint_composer_plugin/` ships **Constraint Studio**, the visual
  constraint manager; retain its `protocol-constraints` package identifier.
  Rule edits are staged against a saved snapshot with reviewed offline apply.
- `bom_studio_plugin/bomstudio/` and `web/` contain BOM services and local UI.
  `quick_pi_plugin/`, `signal_integrity_advisor_plugin/`,
  `trace_impedance_plugin/` and `planar_magnetics_plugin/` own their respective
  numerical models and plugin tests.
- `docs/` holds current guides; `docs/audits/` records validation evidence and
  limitations. `.validation/` is local scratch evidence, not a runtime dependency.
  `pcm/` is the public package feed; `releases/` holds locally built assets.

## Implementation and interface expectations

Use the originating editor's saved project context. Avoid global board state,
fixed ports and shared temporary filenames that break concurrent instances.
Do not hard-code a developer's paths, Python environment or installed libraries.
Use the managed runtime helpers; see [runtime setup](wayricad_runtime/RUNTIME_SETUP.md).
Test missing dependencies and actionable startup errors as well as success.

Keep local UIs task-oriented, with geometry and result feedback before applying
changes. Invalidate stale previews, calculations and exports when inputs change.
Preserve source hashes, backups and the tool's documented undo/offline-apply
contract. Do not bypass native DRC or present condition matching as DRC success.

For physics changes, state units, boundary conditions, material assumptions and
unsupported geometry. Check conservation, analytical references and mesh/time
refinement where applicable. Never turn missing parameters into an unexplained
zero or a fabricated pass. PI is currently 2.5D DC; do not silently claim full
3D or AC support. Research citations must distinguish implemented methods from
future work. Follow the [AI disclosure](ACKNOWLEDGEMENTS.md) for attribution.

## Validation commands and evidence

Use focused affected-plugin tests during development. The complete required CI
matrix and commands live in [.github/workflows/ci.yml](.github/workflows/ci.yml);
consult that file rather than treating a single root test command as full coverage.

```text
python -m pip install -e ".[test]"
python -m pytest tests -q
python -m pytest protocol_constraint_composer_plugin/tests -q
python -m unittest discover -s planar_magnetics_plugin/tests -v
python tools/validate_docs.py --source-only
```

Run BOM tests from `bom_studio_plugin/` with
`python -m unittest discover -s tests -v`; its import context differs from root
tests. Scientific/native tests need their declared dependencies. Native GUI and
pcbnew checks require an actual KiCad installation and the intended runtime
profile. Distinguish a source-tree import, an isolated installed-package check,
a native-window check and an editor-connected workflow. Skips are not passes.
CI on an OS does not establish native GUI compatibility on that OS or KiCad 11.

For documentation-only changes, validate links, preview images and formatting;
do not regenerate published packages merely to update the repository README.

## Packaging and release discipline

1. Align active package versions and release notes for a new software release.
   Build with `python build_pcm.py --clean-feed` and `python -m build`.
2. Run `python tools/validate_packages.py`, `python tools/validate_docs.py` and
   `python tools/smoke_imported_packages.py dist/<built-wheel>.whl`.
   Verify isolated ZIP imports, bundled help/assets and relevant native workflows.
3. Keep candidate feed changes out of the public branch until referenced release
   assets exist. Require passing CI for the release source commit and compare
   uploaded asset hashes against validated local files.
4. Publish only within the user's authorization. Then promote `pcm/pkgs.json`
   and `pcm/repo.json`, and verify public unauthenticated downloads and hashes.
   Do not silently replace binaries under an already published version.
5. `python tools/install_suite.py` previews local installation; `--apply`
   installs with backups when authorized. Verify installed files against ZIPs
   and tell the user when KiCad must restart. Never commit machine-specific
   runtime paths, credentials, user boards or temporary reports.
