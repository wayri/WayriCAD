# Board-derived RLC eye and step response

This describes the development source after release 4.0.0; existing 4.0.0
downloads retain the earlier ideal-line eye.

Quick SI's **Board RLC eye** uses the selected PCB route's ordered sections from
the RLC extractor. It retains each section's resistance, inductance and
capacitance instead of replacing the route with one ideal impedance and delay.
Width changes therefore affect both loss and reflections. This is a linear
channel simulation, not an LPDDR4 interface qualification.

## Set up and run

1. Save the PCB, define the physical stackup and refill reference zones.
2. Select the actual signal net, source pad and receiver pad. The complete net
   must have exactly two signal pads and no unmodelled branches, stubs or zones.
3. Enter the driver's **10–90% rise time** and **Driver resistance**. These are
   linear source assumptions; selecting an IBIS model does not populate them.
4. Open **Setup → Board RLC eye**, or use **Set up path…**. Enable the eye and
   enter the actual **NRZ bit rate** and **open-circuit source swing**.
5. Enter **Receiver resistance** (blank = open) and **Receiver capacitance**
   (blank = 0 pF). Input capacitance is not automatically read from IBIS.
6. For via routes, enter reviewed **loop L per via** and **shunt C per via**.
   Both fields are required. The same symmetric pi equivalent applies to every
   traversed via; use another solver for dissimilar or uncharacterized transitions.
   The extractor's isolated barrel inductance is deliberately not used as loop L.
7. Choose **Run SI**, then **Eye / step**. Hover to inspect samples, click to pin
   probes and right-click to clear them. Export HTML/results through **Files**.
   Saved numerical results retain section values, assumptions and convergence
   diagnostics; loading them does not silently rerun the channel.

| Input / condition | Meaning |
|---|---|
| Track section R/L/C | Comes from the RLC backend's supported microstrip or symmetric-stripline model and actual route dimensions/reference coverage. |
| Nonuniform section impedance | Supported by the cascade, even when one aggregate route Z0 is unavailable. |
| Assumed uniform Z0 / effective Er | Applies to the separate route timing/termination screen, not the board eye. It cannot override missing section extraction. |
| Reviewed via L/C | Explicit user assumptions, combined with extracted barrel DC resistance; total C is divided equally across the two ends. |
| Missing reference, nearby unmodelled copper, unsupported internal stackup | Eye is unavailable with a reason; no automatic fallback to an ideal eye. |
| Branches, stubs, extra pads or signal-zone paths | Need an explicit branched/field model and are rejected by this channel. |

## Channel mathematics

For a uniform section, let its total series impedance be `Z = R + jωL` and
shunt admittance be `Y = jωC`. Define `p = sqrt(ZY)`. Its transmission matrix is:

```text
    [ A  B ]   [ cosh(p)       Z sinh(p)/p ]
M = [      ] = [                         ]
    [ C  D ]   [ Y sinh(p)/p   cosh(p)     ]
```

The code evaluates the analytic `sinh(p)/p → 1` limit at DC. It multiplies
matrices in route order. For receiver admittance `YL = 1/Rload + jωCload` and
source resistance `Rs`, the receiver/source voltage transfer is:

```text
H(ω) = 1 / [A + B YL + Rs (C + D YL)]
```

This includes repeated reflections between different section impedances and
the entered terminations. A via uses a lumped `C/2 → R+L → C/2` pi section.
The line relations follow the [Qucs transmission-line technical
documentation](https://qucs.sourceforge.net/tech/node61.html). The
[ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)
describes the related distributed RLC lossy-line model; Quick SI implements its
own bounded frequency-domain cascade and does not invoke ngspice for this eye.

The source is a cyclic 127-bit PRBS7 waveform with equal linear rising/falling
ramps; ramp duration is `rise_time / 0.8`. FFT multiplication by `H(ω)` gives the
periodic steady-state receiver waveform. The eye is aligned by the sum of
geometric line delays. **Center opening** is minimum high minus maximum low at
0.5 UI, not an optimized receiver sampling result.

## Numerical checks

- Sampling doubles from 64 to 128 samples/UI, then up to 256/512 if necessary.
  Aligned waveform refinement error must be at most 0.5% of source swing, and
  each source ramp must have at least eight samples.
- A separate ramped-step FFT window expands until pre-edge history and the
  settled receiver voltage agree with zero/DC limits within 0.1% of source swing.
  The exported step includes significant ringing through settling.
- There are limits of 512 sections, 16 million frequency-section evaluations
  per transfer and 262,144 step samples. Failure to converge reports unavailable;
  no plausible-looking unconverged eye is substituted.
- Analytical checks cover DC dividers, matched lossless delay, subdivision
  invariance, passive power bounds, receiver RC and an independent nodal via
  equivalent. Native tests cover extraction, changed width, missing planes,
  unmodelled stubs and explicit via assumptions on synthetic board copies.

## Physical limits

This first board channel uses **frequency-independent DC copper resistance**
and quasi-static L/C. Skin/proximity effect, return-conductor loss, copper
roughness and dielectric loss/dispersion are **not included**. A single-frequency
AC resistance is not reused as a broadband physical model. Pad/package spreading,
connector parasitics, coupling, nonlinear IBIS clamps, jitter and noise are also
absent. Any extractor thickness assumptions remain assumptions.

It does not model LPDDR4 read/write switching, ODT changes, training, device
setup/hold requirements or BER. It does not solve a coupled differential channel.
For device-specific IBIS transients, separately assign models, export the KiCad
circuit and run/review its native simulator. The standalone `wayricad-si eye`
command remains the earlier explicitly ideal lossless-line teaching model.

## CLI example

```text
wayricad-si screen board.kicad_pcb --net DATA --start U1.1 --end U2.1 --source-ohm 40 --load-ohm 60 --rise-ns 0.08 --eye-bitrate-mbps 1600 --eye-swing-v 1.1 --eye-load-pf 2 --output data-eye.json --html data-eye.html
```

For a characterized via route, additionally supply `--eye-via-l-nh` and
`--eye-via-c-pf` with the reviewed values. These are also available as
`eye_load_pf`, `eye_via_l_nh` and `eye_via_c_pf` in each multi-net case's `inputs`.
An explicitly requested unavailable eye gives CLI exit code 3.
