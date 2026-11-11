# Research antenna validation record

Date: 2026-11-09  
Host: Windows, Python 3.11, EMerge 3.0.0b9, SUPERLU  
Scope: API construction and deliberately coarse screening; not qualification

The final source gate passed 20 focused research-antenna tests and 317 complete
Quick EMerge tests, with 96 skips for unavailable native wx/VTK/KiCad or
optional runtime coverage. Skips are not passes.

## Completed checks

### Refined sampling and replacement gallery, 2026-11-10

The replacement gallery uses a new 9,240-tetrahedron solve with 21 actual
frequencies over 2.35-2.55 GHz (10 MHz spacing) and a 161 x 161 field grid at
Z = 2 mm. Mesh controls changed from 2.5 to 1.25 mm and resolution 0.35 to
0.22. EMerge 3.0.0b9 / SuperLU completed the sweep in about 516 seconds.
The 2D plots are direct 220-DPI data exports with readable axes and reduced
empty frame space; the 3D views use a larger native framebuffer. The old data
were not upscaled or blurred. Angular radiation sampling remains 2 degrees.

At 2.45 GHz, S11 changed from -0.589195+j0.660815 to
-0.575611+j0.678958, an absolute complex difference of 0.0226645.
The nearly linear boresight axial ratio changed from 50.156 to 92.518 dB;
the new normalized Stokes values are approximately -0.999995, 0.003270,
-0.00004733. This large AR sensitivity near a degenerate line is **not
convergence**. The matching check still fails; no claim of agreement with the
paper is made. Larger boundaries and further mesh refinement remain required.

The [replacement images and provenance](images/dense/provenance.json) and
[gzip-compressed original numerical samples](images/dense/wlan-screening-samples.json.gz)
are separate from the earlier coarse gallery preserved below. The helper's
`verify` mode checks the compressed file's bytes, all image hashes and the
axial ratio against an independent SVD of the real Jones-vector matrix.

### Native result capture run, 2026-11-10

A fresh Yang WLAN screening run solved 2.35/2.45/2.55 GHz using EMerge 3.0.0b9
and SuperLU with 4,429 tetrahedra and a 41 x 41 field plane at Z = 2 mm.
Native Quick EMerge 4.7.0 captured S11, the E-field plane, its 3D display,
the 2D radiation cut and 3D radiation. The matching check failed. The run is
not the earlier 3,371-tetrahedron study and does not supersede convergence work.
The [portable samples](images/wlan-screening-samples.json) and
[capture hashes/runtime provenance](images/provenance.json) preserve its exact
inputs and available results without the local source-path block.

The expanded gallery also captures native top/isometric design geometry, the
design open in the plugin, S11 phase and the Smith chart. A separate numerical
plot derives the polarization ellipse and Stokes parameters from the stored
boresight Ex/Ey: AR = 50.156 dB at 2.45 GHz, nearly linear. This is not a native
polarization-panel screenshot or an AR-bandwidth reproduction. The 2D research
fallback's missing radiator was observed; design top views instead use the
actual native 3D model with its orthographic camera. No fix to that fallback is
claimed by the documentation/capture changes.

### Earlier screening evidence

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
