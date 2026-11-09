# Published antenna benchmarks

These portable Quick EMerge setups reproduce dimensioned antenna geometries
from open academic papers. They are examples and regression benchmarks, not
pre-qualified flight hardware. Open a setup from **Files > Open setup**, review
the geometry and assumptions, then run it in an isolated EMerge runtime.

| Setup | Source | Intended check |
|---|---|---|
| `rezaeipour-2021-dual-feed-patch.json` | Rezaeipour and Sadeghzadeh (2021) | Linear/RHCP/LHCP coherent feeds and boresight axial ratio |
| `yang-2016-wlan-monopole.json` | Yang et al. (2016) | Printed 2.4/5 GHz WLAN return-loss bands |
| `liu-2020-cubesat-yagi.json` | Liu et al. (2020) | Planar CubeSat printed Yagi and balanced coplanar feed |
| `verho-2023-aesa-4x4.json` | Verho et al. (2023) | 3 GHz 4x4 scan law and steering error |
| `kabir-2023-cubesat-sx.json` | Kabir et al. (2023) | Stacked S/X-band CubeSat shared aperture, isolation and circular polarization |

## Evidence boundaries

The `research` block in every result records the title, DOI, source dimensions,
published targets and the implemented model scope. `publication_comparison`
checks only observables present in both the run and the paper. A passing sampled
comparison is not convergence evidence.

The AESA setup evaluates the published rectangular-array phase law. It does not
invent varactor, PIN-diode or feed-network losses. The Yagi setup omits the
CubeSat body and deployment angle, so its 10°, 50° and 90° measured states are
retained as evidence but are not claimed as planar-model predictions. The
dual-feed patch excludes the reconfigurable feed network. The S/X setup includes
the two RT/duroid 5880 layers, 16.2 mm air cavity, RT/duroid 6010 superstrate,
two probe feeds and the dimensioned radiators; bolts and SMA bodies are omitted.
The patch's `auto` state is the paper's equal-amplitude, equal-phase linear
excitation. Circular-state handedness is retained as signed Stokes S3 until the
solver and paper propagation conventions are independently reconciled.

## Reproducing setups from the CLI

```text
python -m quick_emerge_plugin --list-research-antennas "*satellite*"
python -m quick_emerge_plugin --show-research-antenna kabir-2023-cubesat-sx-shared-aperture
python -m quick_emerge_plugin --write-research-setup kabir-2023-cubesat-sx-shared-aperture sx.json
python -m quick_emerge_plugin --array-scan verho-2023-aesa-4x4 35 --array-phi 0
```

For the shared-aperture antenna, run narrow S-band and X-band sweeps separately
and select the matching excitation. The broad generated setup is for discovery,
not an efficient final solve.

## Sources

- Rezaeipour and Sadeghzadeh, *A Multi Polarization Square Patch Antenna with a Reconfigurable Feeding Network*, 2021. <https://arxiv.org/abs/2106.07291>
- Yang et al., *Design of Miniaturized Dual-Band Microstrip Antenna for WLAN Application*, 2016. <https://doi.org/10.3390/s16070983>
- Liu et al., *A Printed Yagi Antenna for CubeSat with Multi-Frequency Tilt Operation*, 2020. <https://doi.org/10.3390/electronics9060986>
- Verho, Nguyen and Chung, *A 4 x 4 Active Antenna Array with Adjustable Beam Steering*, 2023. <https://doi.org/10.3390/s23031324>
- Kabir, Khan and Latif, *A Multi-Band Circularly Polarized-Shared Aperture Antenna for Space Applications at S and X Bands*, 2023. <https://doi.org/10.3390/electronics12214439>

See [VALIDATION.md](VALIDATION.md) for completed screening runs and unresolved
paper-agreement work.
