# Published SIW, resonator and horn reconstruction audit

The SIW/DRA and PCB-horn sources now have executable, assumption-bearing
geometry builders and portable setups. Geometry commits passed; their FEM
screening/comparison is a separate gate. The standalone circularly polarized
resonator remains an audited candidate, not an implemented replica. Do not
advertise any paper's plots as Quick EMerge results. See the
[execution guide](PAPER_RECONSTRUCTIONS.md).

## SIW and dielectric resonator

Cheh Lin, Jamaluddin and Gaya (2023), *A Triple Band Substrate Integrated
Waveguide with Dielectric Resonator Antenna for 4G and 5G Applications*,
[DOI: 10.3390/mi14071284](https://doi.org/10.3390/mi14071284).
[Author-university copy](https://eprints.utm.my/105814/1/MohdHaizalJamaluddin2023_ATripleBandSubstrateIntegratedWaveguide.pdf).

Figure 1 and Table 1 were visually inspected. Source dimensions include a
40 x 40 x 21 mm resonator (Er 10, tan delta 0.0019), 1.6 mm FR4 (Er 4.6,
tan delta 0.019), 4 mm vias at 8 mm pitch, and a U-slot coupling structure.
The measured matching bands reported near 1.8/2.6/3.7 GHz are comparison
targets, not plugin results. An exact coordinate audit of the U-slot offsets,
taper and via endpoints is required before meshing; table parameters alone
do not specify every origin convention.

The independent coordinate audit puts the main-region centre at (0,0): the
board spans x=[-32,32], y=[-57,28] mm; the DRA footprint spans x=[-20,20],
y=[-22,18] mm. This matches the stated 6/10/12 mm clearances. Equation (7)
evaluates to 49.871 mm using Table 1 values, not its listed 56 mm SIW width.
Via-lattice phase and U-arm/bar endpoint conventions remain assumptions. A
generic broadside pattern would also miss the reported tilted 2.6 GHz E-plane
maximum. Full-wave construction must preserve those uncertainties.

## Circularly polarized resonator

Illahi et al. (2022), *A Novel Design and Development of a Strip-Fed Circularly
Polarized Rectangular Dielectric Resonator Antenna for 5G NR Sub-6 GHz Band
Applications*, [DOI: 10.3390/s22155531](https://doi.org/10.3390/s22155531).

Figure 1 was visually inspected. The source specifies an Er-10 resonator with
H/W/D = 26.1/25.4/14.3 mm and a five-segment conformal strip. The final strip
lengths are 5.5, 7, 5, 10 and 1.5 mm. Feed-strip width and the idealized connector
gap must be audited rather than silently invented. Compare reflection, complex
boresight polarization and principal cuts; a circular-looking animation is not
an axial-ratio validation.

## PCB SIW horn

Ma et al. (2024), *A 60 GHz Slotted Array Horn Antenna for Radar Sensing
Applications in Future Global Industrial Scenarios*,
[DOI: 10.3390/mi15060728](https://doi.org/10.3390/mi15060728).

Figures 1/2/7 and Table 2 are the geometry reference. Figure 1 was visually
inspected. The source uses Arlon AD255C, Er 2.55, tan delta 0.0014, a 0.508 mm
substrate, and 0.3 mm vias at 0.6 mm pitch. The output width is 13 mm. Its slots,
metal-cut transition and radiation belts must be reconstructed, not replaced
by an ideal solid-wall horn. Reconcile the different width/length labels and
the rounded overall dimensions before defining the final mesh domain.

## Acceptance steps

1. Record source PDF hashes and audited parameter/coordinate provenance.
2. Construct source-faithful dielectric volumes, metal sheets, plated-via
   boundaries, feed transition and ports. Declare every idealization.
3. Verify geometry against the paper figures before solving. Export the actual
   geometry, not a decorative model.
4. Run narrow frequency sweeps and at least two mesh/air-boundary refinements;
   retain failures and solver diagnostics.
5. Compare sampled S-parameters, resonances, polarization and radiation cuts
   against the paper, with explicit tolerances and digitization uncertainty.
6. Show original complex E/H phase vectors inside the guide/resonator and
   around the aperture at physically registered coordinates. Show far-field
   lobes separately; relative field is not realized gain.
7. Add screenshots and offline interactive results only from completed runs.
   A geometry-only or unconverged screening result must retain that status.

All three papers are open-access research. Citations establish source lineage,
not agreement or independent physical validation.
