# WayriCAD repository guide

This guide provides project context for contributors and coding assistants.
Read [CONTRIBUTING.md](CONTRIBUTING.md) for contribution requirements and the
affected plugin's README for its workflow, supported inputs and limitations.

## Project structure

WayriCAD is a suite of independently installable KiCad plugins. The default
branch is `develop`; open contribution branches and pull requests against it.

| Location | Purpose |
|---|---|
| `*_plugin/metadata.json` | Active plugin inventory and PCM metadata; some other plugin directories contain retired source |
| `wayricad_runtime/` | Shared launchers, IPC integration, managed runtimes and CLI support |
| `build_pcm.py` | Builds independent PCM ZIPs and candidate repository metadata |
| `bom_studio_plugin/bomstudio/` and `bom_studio_plugin/web/` | BOM services and local web interface |
| `protocol_constraint_composer_plugin/` | Constraint Studio, including the visual rule editor and staged project workspace |
| `quick_pi_plugin/`, `signal_integrity_advisor_plugin/`, `trace_impedance_plugin/`, `planar_magnetics_plugin/` | Electrical and magnetic analysis implementations and their tests |
| `tests/` and plugin `tests/` directories | Shared regression tests and plugin-specific suites |
| `docs/` and `docs/audits/` | User/developer guides and recorded validation evidence |
| `tools/` | Installation, packaging and validation utilities |
| `pcm/` | Public KiCad package repository feed |
| `releases/` | Locally built release assets |

Constraint Studio retains the `protocol-constraints` package identifier.
Use active metadata and the [plugin catalogue](README.md#all-16-plugins) when
changing names or inventory; directory names do not always match product names.

## Local development

Use Python 3.10 or newer and a virtual environment for source development:

```text
python -m venv .venv
```

Activate that environment using your platform's normal command, then install:

```text
python -m pip install -e ".[test]"
```

Scientific and native GUI workflows have additional dependencies. Consult
[runtime setup](wayricad_runtime/RUNTIME_SETUP.md) and the affected plugin's
requirements. KiCad's native Python bindings and wxPython are not supplied by
the editable package install. Never commit a local virtual environment,
credentials, machine-specific paths or private project data.

## Architecture and behaviour

- Each installed plugin must work independently. The builder vendors shared
  runtime code into ZIPs; plugins cannot import sibling packages from a source
  checkout after installation.
- Use the originating editor's project context. Avoid global board state,
  fixed ports or shared temporary filenames that break concurrent instances.
  Keep runtime discovery portable and dependency failures actionable.
- Keep application interfaces local and task-oriented. Show geometry and result
  previews before writes; clear stale previews and exports when inputs change.
- Preserve the affected tool's source-hash checks, backup, undo and offline-apply
  contracts. Constraint Studio edits a saved snapshot and exports reviewed
  changes. Condition matching is not native DRC acceptance.
- Preserve existing third-party licenses and provenance. Follow the
  [AI-assisted contribution guidance](CONTRIBUTING.md#ai-assisted-contributions)
  and [acknowledgements](ACKNOWLEDGEMENTS.md).

## Testing and validation

Start with the affected tests. Examples from the repository root:

```text
python -m pytest tests -q
python -m pytest protocol_constraint_composer_plugin/tests -q
python -m unittest discover -s planar_magnetics_plugin/tests -v
python tools/validate_docs.py --source-only
```

Run BOM tests from `bom_studio_plugin/` using
`python -m unittest discover -s tests -v`. Its import context differs from root
tests. The complete automated matrix is defined in
[CI](.github/workflows/ci.yml); root tests alone are not the entire suite.

Record the OS, KiCad version, runtime and checks actually performed. Distinguish
source imports, isolated ZIP/wheel checks, native-window tests and workflows
connected to a running editor. Skipped tests are not passes. Automated CI does
not establish native GUI compatibility on every OS or KiCad version; consult
[compatibility](docs/COMPATIBILITY.md).

For numerical changes, document units, material assumptions, boundary conditions
and unsupported geometry. Use analytical references, conservation checks and
mesh/time refinement where applicable. Preserve unknown or approximate results
instead of supplying misleading defaults. Current PI is 2.5D DC; research
citations must distinguish implemented methods from future capabilities.

For documentation-only changes, check links, images and formatting. Published
binaries do not need rebuilding for a repository README update.

## Packaging and maintainer releases

1. Align active package versions and release notes for a new software release.
   Build with `python build_pcm.py --clean-feed` and `python -m build`.
2. Run `python tools/validate_packages.py`, `python tools/validate_docs.py` and
   `python tools/smoke_imported_packages.py dist/<built-wheel>.whl`.
   Check independent ZIP imports, bundled assets and affected native workflows.
3. Keep generated candidate feed changes out of the public branch until the
   referenced assets are published. Release the source commit that passed CI;
   verify uploaded assets against local hashes.
4. Maintainers publish releases and then promote `pcm/pkgs.json` and
   `pcm/repo.json`. Verify public downloads and hashes. Do not silently replace
   binaries under an already published version.
5. `python tools/install_suite.py` previews a local installation. `--apply`
   installs with backups; restart KiCad afterward and verify the installed
   plugins. Keep local test reports and user boards out of release assets.

Include reproduction steps, relevant test results, limitations and screenshots
for UI changes in pull requests. Update the affected plugin's README and offline
help when its user-facing behaviour changes.
