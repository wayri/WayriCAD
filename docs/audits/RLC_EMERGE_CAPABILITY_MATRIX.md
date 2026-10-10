# RLC impedance capability matrix — EMerge model integration

Checked on Windows with KiCad 10.0.6's bundled Python 3.11 and source branch
`rlc-emerge-models`. This distinguishes *board-extracted geometry* from
*manually entered cross sections*. Neither constitutes protocol compliance or
a measurement of a fabricated board.

The scalar line models are ported from the corrected [EMerge PCB calculator
PR](https://github.com/wayri/EMerge/pull/1) at `50283a2` into this PCM package
without adding NumPy/SciPy as an install-time dependency. The two repos do not
share runtime imports; each plugin ZIP remains independent.

| Geometry / result | Board path | Manual cross section | Checked result | Remaining condition |
| --- | --- | --- | --- | --- |
| Surface microstrip, single-ended Z₀ | **Works** when a saved homogeneous stackup and adjacent filled reference are verified | **Works** with width, copper, height, Er | RFsim 2.9/1.53/0.035 mm, Er 4.5: **49.753 Ω** vs independent 49.8 Ω (−0.09%) | Quasi-static uniform section; no mask/loss/transition field solve |
| Centered symmetric stripline, single-ended Z₀ | **Works** only with two verified symmetric reference planes | **Works** with width, copper, plane spacing, Er | RFsim 0.6/1.53/0.035 mm, Er 4.5: **50.590 Ω** vs independent 50.249 Ω (+0.68%) | Asymmetric or heterogeneous stackups need field solving |
| Coplanar waveguide (CPW), single-ended Z₀ | **Unknown**: side-ground slot/continuity is not extracted | **Works as estimate** with explicit slot, zero copper thickness | EMerge reference: 1.5/0.3/1.53 mm, Er 4.5: **57.643 Ω** | Infinite symmetric lateral ground assumed |
| Grounded CPW / CPWG, single-ended Z₀ | **Unknown**: nearby lateral copper still blocks plain microstrip | **Works as estimate** with explicit side slot and lower ground, zero copper thickness | RFsim geometry: **50.942 Ω** vs independent 50.977 Ω (−0.07%) | Lower and lateral grounds must actually be continuous; thickness/mask omitted |
| Edge-coupled centered stripline, differential Z₀ | **Unknown**: pair spacing and continuous coupled geometry are not extracted | **Works as estimate** with explicit pair gap, zero copper thickness | EMerge reference: 0.2 mm width, 0.2 mm gap, 0.8 mm cavity, Er 4.2: **108.495 Ω** | No bends, skew, via transitions or channel loss in modal estimate |
| Differential microstrip / grounded differential CPW | **Unknown** | **Unknown** | EMerge's differential CPW shortcut was disabled after failing a common-mode limiting case | Qualified coupled solver plus gap and return geometry required |
| Asymmetric internal line, broadside pair, embedded/offset stripline | **Unknown** | **Unknown** | No supported input/model combination in RLC | Field solver or validated additional geometry model required |
| Via, zone and mixed path total Z₀ | **Unknown** as one uniform impedance | Not applicable | Via partial R/L and zone corridor R/L/C remain separate estimates | Transition/return field and terminal-dependent geometry required |

## Board evidence and limitations

- The saved Berkeley Marble `/ETH_PHY/MDI0_P` route, J4.11 → U4.28, had
  124 track sections. One lacked verified reference copper; the report remained
  `partial` with **null global Z₀**. Modeled sections used the new microstrip
  estimate (one 0.13 mm section was 60.256 Ω), while the unsupported section
  stayed null. Board bytes were unchanged in the native window smoke test.
- RFsim's public layout generator provides geometry and separate analytical
  references; its generated boards do not save usable dielectric properties
  in KiCad Board Setup. Automatic reports therefore remain partial/null on
  those files. The numerical comparisons above use the generator's declared
  material dimensions manually; they do not claim successful automatic
  extraction or measured fabrication accuracy.
- The 100 MHz default in the board analyzer affects AC conductor resistance.
  The new Z₀ estimates are **quasi-static**; changing that frequency does not
  validate USB, DDR, PCIe, Ethernet or any other signalling rate. Protocol
  pass/fail needs actual channel, source/load, transition, loss and receiver
  requirements. CPWG is especially sensitive to finite ground, copper profile,
  soldermask and via stitching, which this calculation omits.

## Checks run

| Check | Result |
| --- | --- |
| Pure regression cases for five cross sections, invalid inputs and boardless CLI | 9 passed (alongside 6 other focused tests) |
| Existing KiCad-native hybrid geometry suite | 17 passed |
| Native wx window on saved Marble board, including new cross-section tab | Passed; source SHA unchanged |
| Native KiCad Python `cross-section` CLI, grounded CPW case | Passed; 50.942 Ω and labelled assumptions |
| Root repository suite | 332 passed, 68 skipped, 141 subtests passed; skipped checks are not counted as passes |
| Independent PCM ZIP contents | Trace RLC and Quick SI both contain their own corrected scalar engine |

Numerical references: [EMerge corrected source](https://github.com/wayri/EMerge/pull/1),
[RFsim validation generator and equations](https://github.com/NBalciunas/kicad-rfsim/tree/efa0ea9bd34b13f7819c6f2d4c02e78d34b116c3/validation),
and [Qucs CPW conformal formulas](https://qucs.github.io/tech/node86.html).
