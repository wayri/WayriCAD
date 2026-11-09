# Research antenna validation record

Date: 2026-11-09  
Host: Windows, Python 3.11, EMerge 3.0.0b9, SUPERLU  
Scope: API construction and deliberately coarse screening; not qualification

The final source gate passed 20 focused research-antenna tests and 317 complete
Quick EMerge tests, with 96 skips for unavailable native wx/VTK/KiCad or
optional runtime coverage. Skips are not passes.

## Completed checks

All five setup records pass the bounded configuration validator. Four full-wave
geometries construct and commit using the public EMerge API. The 4x4 AESA scan
law passes deterministic broadside and 35° steering tests with less than 0.26°
grid error.

The Yang WLAN geometry completed a 3,371-tetrahedron, three-frequency screening
solve at 2.35/2.45/2.55 GHz. The sampled S11 values were approximately
`-0.715+j0.537`, `-0.598+j0.635`, and `-0.463+j0.708`. This coarse mesh did not
demonstrate the paper's -10 dB band and is recorded as a failed comparison, not
as contradictory evidence.

The source figure uses x downward and y to the right. After explicitly mapping
those axes to the solver coordinates, the Kabir shared-aperture S-band path
completed a 10,916-tetrahedron screening solve at 2.00/2.04 GHz. S11 was
approximately `0.062+j0.032` and `-0.786-j0.162`; boresight AR at 2.04 GHz was
23.74 dB. The sampled publication comparison failed.

The corrected X-band path completed a 12,105-tetrahedron screening solve at
8.40/8.50 GHz in 105 seconds. X-port S22 was approximately `-0.877+j0.276` and
`-0.863+j0.362`; boresight AR at 8.50 GHz was 24.30 dB. This also fails the
paper target on the coarse mesh. Earlier meshes generated before the coordinate
audit are discarded and are not comparison evidence.

## Required before claiming paper agreement

1. Run separate narrow sweeps around each reported resonance and AR band.
2. Perform at least three mesh levels and two air-boundary distances.
3. Confirm dielectric loss/dispersion and copper finish against the paper.
4. Compare probe/connector models and port de-embedding planes.
5. Report resonance, bandwidth, isolation, axial ratio and gain with the same
   definitions and angular conventions used by the source.

No committed example claims gain validation because current Quick EMerge
radiation output is relative field magnitude, not accepted-power-normalized gain
or efficiency.
