# Protocol Discovery and Screening

## Native Workflow

Save the PCB, project and custom rules first. Open Trace RLC and choose
**Protocol scan...**, then **Discover and check**. This reads saved copper in a
separate native process; it does not include unsaved editor changes. Cancellation,
timeouts and a failed native worker do not apply changes to the PCB.

Sort the candidate table by its headers. Select a row to read its matching
evidence, section IDs, layers, blockers and corrective suggestions. Double-click
to load that net into the parent analyzer. Live-board highlighting is available
only when the parent is connected to the originating editor, not a saved-board
session. Choose explicit start/end pads there for a route-specific review.

The frequency is an analysis input, not a bit rate inferred from a protocol name.
The target tolerance is an editable screening assumption, not a standards limit.
Export writes HTML plus paired JSON evidence. Source PCB/project/rule changes
invalidate the report and require a new scan.
Paired publication uses the shared rollback mechanism: an I/O failure restores
previous approved HTML/JSON outputs rather than leaving a mixed report pair.

## Families

| Category | Candidate naming families |
|---|---|
| Ethernet | RGMII, SGMII, Ethernet MDI, 10GBASE-KR |
| Memory and parallel | DDR2/3/4/5, LPDDR4/5, parallel PCI, GPIO |
| Serial links | PCIe, SerDes, FPGA GTH/GTY/GTX/GTP, SATA, LVDS |
| Peripheral links | USB2/3/4, CAN/CAN FD, RS485, I2C, SPI/QSPI, UART/USART, I2S/TDM, SDIO |
| Display and RF | HDMI/TMDS, DisplayPort/eDP, RF |

M.2 is flagged for interface review because a connector name does not determine
the electrical interface. DDR differential clock/strobe naming is paired when
polarity is explicit; data and address lines remain single-ended candidates.
Names such as `GTH_TXP0` and `GTHTXN0` retain lane and hierarchical scope. Generic
TX/RX names alone are not enough to establish a protocol. Pin functions and
operating rates are not inferred from label spelling.

Token matches tolerate separators and case. Bounded one-edit fuzzy matching is
restricted to longer alphabetic aliases and always requires review. Conflicting
profiles and multiple possible mates are retained as ambiguities, not silently
selected. Power-like labels are excluded. Review unclassified nets too: absence
from this table is not evidence that the board is safe.

## Custom Naming and Targets

Expand **Custom matching rules and impedance targets**. Rules are a JSON array:

```json
[
  {"kind":"wildcard", "pattern":"*/RADIO_FEED*", "profile_id":"rf"},
  {"kind":"regex", "pattern":"^SENSOR_SPI[0-9]_", "profile_id":"spi"}
]
```

Wildcards support `*` and `?`. Regex deliberately disallows groups, alternation,
backreferences and counted repetition, and permits at most one variable repeat.
There are at most 32 rules, 128 characters per pattern and 10,000 input nets.
Use multiple simple rules instead of an expensive expression. A custom rule does
not override conflicting identity evidence; rename or review that conflict.

Target overrides map an exact net or profile ID to positive ohms; exact nets win:

```json
{"rf":50, "/RADIO/RF_OUT":50, "rgmii":50}
```

Obtain actual limits from the endpoint manufacturer and stackup fabricator.
CAN/RS485 cable termination values are not automatic PCB impedance targets.
DDR, PCIe generations and FPGA transceiver applications need device-specific
requirements. No universal target is assigned to them.

## CLI and Automation

Run using KiCad's Python or a configured suite CLI runtime with `pcbnew`:

```text
wayricad-rlc protocol-profiles
wayricad-rlc protocols Example.kicad_pcb --rules rules.json --targets targets.json --frequency-mhz 100 --tolerance-pct 10 --max-nets 500 --max-sections 5000 --output protocol-screen.json
```

For source development the equivalent entry point is
`python -m trace_impedance_plugin.cli`. `protocol-profiles` requires no board.
Rules/targets files are bounded to 1 MiB each. JSON contains the original board
SHA-256, source file fingerprints, every candidate and ambiguity, per-section
geometry/model evidence, omissions and corrective suggestions. Budgets never
turn truncated extraction into a passing report.

Exit codes: **0** means every candidate is within its supported single-ended
screening target, **1** means an input/runtime error, **2** means at least one
target violation, and **3** means review, unsupported/incomplete evidence or no
candidates. None of these codes certifies protocol compliance. Automation should
retain the JSON and reject 1/2/3 for review, without silently rewriting a board.

## Interpretation and Limits

Automatic impedance screening uses the existing supported single-ended
microstrip/centered-stripline section models and saved filled-reference geometry.
Suggestions to increase/decrease width or reference separation indicate a
direction for a reviewed design sweep, not a guaranteed corrective dimension.
Multiple terminals flag a *possible* branch/stub, not a measured stub length.
Vias flag discontinuity review; antipad and return-path terms may remain unknown.

**Differential candidates never receive an automatic coupled-impedance pass.**
Twice single-ended impedance is not substituted for differential impedance.
Pair gaps, coupling, receiver timing, skew limits, eye masks, termination states,
AC reference connectivity and package/connector effects require additional
models or external tools. I2C pull-up/rise-time design remains in Quick SI.

References for context: [TI high-speed layout guide](https://www.ti.com/lit/an/slla414/slla414.pdf)
and [TI CAN physical-layer guidance](https://www.ti.com/lit/an/slla270/slla270.pdf).
Profile-specific source links are retained in `protocol-profiles`; nominal
values are hints, not a claim to implement every requirement in those documents.

## Troubleshooting

- **No candidates:** inspect the net inventory and add explicit wildcard rules.
- **Needs review:** inspect evidence and endpoint data; ambiguous/fuzzy matches
  are not automatically extracted or approved.
- **Missing mate:** check polarity, lane and hierarchy. Do not combine instances.
- **Unknown Z0:** supply real stackup data and verify filled reference copper;
  unsupported geometries remain unknown rather than using generic FR-4.
- **Worker failed/timed out:** the parent remains open. Reduce budgets, retain
  the diagnostic and retry on a minimal saved board; do not accept partial data.
- **Source changed:** save/reload and scan again. Exporting stale evidence is
  intentionally blocked.
