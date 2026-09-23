# Quick SI and Nubis SignalIntegrity

The next-release integration is a **CLI interoperability phase**, not a claim
that the whole upstream application has been reimplemented in Quick SI.
Quick SI can export a screened route as an ideal lossless Touchstone two-port
and read measured or simulated Touchstone networks using the actual optional
Nubis SignalIntegrity library. An explicit desktop command opens the complete
upstream application in its own process. Existing Quick SI screens remain
dependency-free.

## Reproducible upstream baseline

Reviewed on 2026-09-23:

- [Nubis SignalIntegrity](https://github.com/Nubis-Communications/SignalIntegrity),
  source revision `1922a1591100700aa8bd635964cd688012b8668d`.
- Published Python distribution `SignalIntegrity==1.5.2`, installed only into a
  local validation directory for testing. This is the tested version, not a
  claim about unverified future releases.
- [Setup and dependencies](https://github.com/Nubis-Communications/SignalIntegrity/blob/1922a1591100700aa8bd635964cd688012b8668d/setup.py):
  NumPy, SciPy, matplotlib, Pillow, urllib3, setuptools and pip. The complete
  application also uses Tk. A Python package install alone cannot guarantee a
  working desktop Tk runtime on every OS.
- [License](https://github.com/Nubis-Communications/SignalIntegrity/blob/1922a1591100700aa8bd635964cd688012b8668d/LICENSE.txt):
  GPL-3.0-or-later; source notices credit Nubis Communications (2021) and
  Teledyne LeCroy (2018–2020). The library author is Peter J. Pupalaikis.
  No upstream source is copied or vendored by this phase. Redistributors who
  later bundle it must retain its copyright/license notices and provide the
  corresponding source and dependency notices required for that distribution.

## Use the implemented bridge

Use the Python environment that runs `wayricad-si`; no package is installed or
downloaded during analysis. A dedicated environment keeps scientific packages
separate from KiCad's embedded interpreter:

```text
python -m venv .venv-si
# Activate .venv-si using the platform's normal command.
python -m pip install -e .
python -m pip install SignalIntegrity==1.5.2
wayricad-si network C:/Projects/Example/channel.s2p --to-port 2 --from-port 1 --output channel.json
```

The input must be Touchstone 1.0 S parameters with one explicit option line,
real positive common reference impedance, strictly increasing nonnegative
frequencies, at most 32 ports, 10001 records and 16 MiB. RI, MA and DB formats
and Hz/kHz/MHz/GHz units are supported. Touchstone 2.0, noise records and
project files are not accepted by this adapter. Reports retain the file SHA-256,
upstream version, frequency grid, selected complex S response, magnitude in dB
and wrapped phase in degrees. Exactly zero magnitude has null dB and phase;
null is not a zero-dB response. Port numbers are one-based; use `--to-port 1`
for a one-port file or S11 reflection. The report does not automatically attach
the network to a PCB net or turn S21 into a compliance decision.

To export a saved complete Quick SI route report:

```text
wayricad-si line-network route.json --stop-hz 1000000000 --points 1001 --reference-ohm 50 --output ideal-line.s2p
wayricad-si network ideal-line.s2p --output ideal-line.json
```

The first command needs no upstream dependency. The 1 GHz stop frequency is an
explicit example, not a limit inferred from the board. The exported model has
port 1 at the selected source and port 2 at the selected receiver. It uses the
report's uniform Z0 and one-way delay, equal real port references, and a uniform
frequency grid including DC. The boundary condition is a linear, reciprocal,
lossless transmission line. Its file header labels it **not extracted board
S-parameters**. Source/load resistances, vias, reference transitions, stubs,
coupling, dielectric and conductor losses are not included. More than two
terminals, zone corridors and incomplete reports are rejected. Existing report
assumptions and board hash, when present, are retained in comments. Export works
on the saved report snapshot and does not verify the current PCB revision.

After installing the complete upstream distribution, use the bridge to check
its desktop dependencies or run the full original application:

```text
wayricad-si desktop --check
wayricad-si desktop
wayricad-si desktop C:/Projects/Example/channel.si --python C:/Projects/Example/.venv-si/Scripts/python.exe
```

`--python` selects a dedicated interpreter without changing KiCad's runtime.
`--check` imports the full upstream desktop in an isolated child and reports its
version; it does not open a window or prove that a display server works. The
launch command waits until the desktop closes and reports nonzero exits as
errors. Its diagnostic output remains visible. Open only trusted `.si` projects:
upstream projects support equations and remain under the upstream execution and
save behavior. This is the complete external application, not a native Quick SI
reimplementation. Its `ERL`, `PZ` and `IXT` console utilities remain available
through their original commands in the installed upstream environment. Quick SI
does not validate all of those workflows. Network reports and exports run
offline after installation. For disconnected installation, prepare a wheelhouse
for the destination OS/Python with every dependency, then install with
`--no-index --find-links <wheelhouse>`. Upstream online help is not bundled in
Quick SI; retain upstream documentation separately when deploying offline.

## Capability roadmap and acceptance gates

| Upstream capability | This phase | Work required for native Quick SI integration |
|---|---|---|
| Touchstone and frequency responses | Actual upstream decoding and selected-port complex response; ideal route export | Native plots, explicit board/net/port mapping, mixed-mode conventions, fixture reference planes |
| Network solvers, device models, parsers and symbolic systems | Available only through upstream | Reviewed topology editor and model schemas; calibration fixtures and analytical multiport reference tests |
| Time-domain waveforms, filters, PRBS and eye analysis | Existing Quick SI illustrative eye remains its separate ideal model | Waveform import, sample-time/causality contracts, driver/receiver models, deterministic comparison with upstream |
| Deembedding, virtual probing, measurement calibration, calibration kits and TDR | Upstream workflows only | Required fixture/measurement inputs, unit-aware forms, rank/conditioning diagnostics and known calibration standards |
| Impedance profiles, fitting, noise, optical models and transforms | Upstream library only | Per-domain inputs, uncertainty, unsupported-case handling and reference validation |
| ERL, PZ and IXT utilities | Upstream command-line tools only | Tool-specific input contracts, result schemas, limits and independently verified examples |
| Full desktop schematic/project workflow | Explicit `desktop` command with import preflight and isolated upstream process | Tk/GUI lifecycle isolation, project dependency resolution, trusted project execution policy, versioned installation and native OS testing |

Automatic PCB extraction cannot supply missing driver models, fixture data,
receiver characteristics or full coupled interconnect S parameters. A GUI
launcher or renamed ideal eye cannot satisfy those requirements. For a future
bundled phase, first freeze the upstream version/dependency hashes and licenses,
build isolated platform runtimes, and validate independently installed PCM ZIPs.
Then deliver the native multiport view and model mapping before advanced
simulation and measurement tabs. Each capability needs its own numerical
reference cases and native-window workflow evidence before release claims.

## Validation performed

Windows, Python 3.14.2, actual SignalIntegrity 1.5.2 numerical library:
twelve focused tests passed (plus ten subtests). The matched line agrees with
`exp(-j 2 pi f delay)`, a 100-ohm quarter-wave line at 50-ohm references gives
S11 = 0.6 and S21 = -0.8j, and lossless power conservation is checked over a
frequency sweep. Actual upstream import verifies Hz, port ordering, zero
reflection, complex phase and reference impedance. Invalid/incomplete data,
unsupported topology and missing dependencies are tested.

The ordinary-Python Quick SI suite passed 47 tests, with three skips (one native GUI and
two optional upstream checks); focused tests were also run separately with the actual
upstream dependency so that its skip is not used as acceptance evidence. The actual full desktop import/version preflight also passed; launch argument
handling and failure propagation were tested without opening a window. No
native KiCad window, upstream desktop window, all-platform or published PCM validation was
performed for this phase.
