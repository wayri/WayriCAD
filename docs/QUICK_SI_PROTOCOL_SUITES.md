# Quick SI protocol suites

Protocol suites collect reviewed Quick SI routes and compare them against **your engineering budgets**. They help organize interface review; they do not certify a protocol. Available in 3.2.0 through the native window and `wayricad-si` CLI.

## Native workflow

1. Save the PCB and screen one connected source-to-receiver path in **Quick SI**. Inspect its route and reference-layer evidence; enter actual driver rise time, source/load resistance and any explicit impedance/permittivity assumptions.
2. Open **Protocol suites**, select the actual interface, and choose **Add current Quick SI path**. This adds a snapshot of that screened result. Repeat for each distinct route.
3. Assign each snapshot a role and group. Differential lanes require exactly one `P` and one `N` in the same group, such as `lane0`. A synchronous bus group requires exactly one `clock` and at least one `data` route, such as `byte0`. For DDR DQ review, use the relevant strobe route as that group’s clock; this does not model a coupled differential strobe.
4. Expand **Optional engineering budgets** only when you have justified limits. Enter any of the four budgets below, then run the suite. Blank budgets remain unknown; they do not become implicit passes.
5. Review the checks, native route preview and optional illustrative eye/step evidence. Export local HTML or JSON. Changing assignments or budgets requires a fresh review.

Snapshots must describe the same saved PCB revision. If the board changes, reopen/rescreen the affected paths together. Do not reuse a previous snapshot by changing its recorded hash. Duplicate reports of the same net/start/end route do not constitute an independent pair.

| Budget | CLI option | Compared quantity |
|---|---|---|
| Maximum route delay | `--max-delay-ns` | One-way propagation-delay estimate, ns |
| Maximum group skew | `--max-skew-ps` | Largest delay difference relative to P/clock within its group, ps |
| Maximum impedance deviation | `--max-impedance-error-percent` | Single-ended Z0 deviation from an applicable profile target |
| Maximum delay/rise ratio | `--max-delay-to-rise-ratio` | Propagation delay divided by the entered driver rise time |

Budgets must be finite, nonnegative numbers. Group skew excludes package, transmitter, receiver, clock insertion and setup/hold delays. A profile’s nominal impedance is a routing reference, not an automatic tolerance.

## Profiles

Use `wayricad-si profiles` to inspect current entries, source references, topology, representative rate and limitations.

| Interface | Profile IDs |
|---|---|
| I2C | `i2c-standard`, `i2c-fast`, `i2c-fast-plus` |
| Device-defined serial/parallel buses | `spi`, `uart`, `i2s-tdm`, `parallel-gpio`, `sdio` |
| CAN, LVDS, generic SerDes | `can-classic`, `lvds`, `serdes-nrz` |
| Legacy parallel PCI | `pci-33` — 33 MHz; distinct from PCI Express |
| PCI Express | `pcie-gen1`, `pcie-gen2`, `pcie-gen3`, `pcie-gen4` |
| SATA | `sata-1-5`, `sata-3`, `sata-6` |
| USB | `usb2-fs`, `usb2-hs`, `usb3-gen1`, `usb3-gen2` |
| DDR DQ examples | `ddr3`, `ddr4`, `ddr5` — representative 1600/2400/4800 MT/s |
| Ethernet interfaces | `rgmii`, `sgmii`, `10gbase-kr` |
| M.2 interfaces | `m2-pcie-gen3`, `m2-pcie-gen4`, `m2-sata-6` |

The plain `m2` entry deliberately blocks screening until an actual interface is chosen: M.2 is a form factor, not one electrical protocol. The catalog does not cover every interface revision or M.2 use. Choose the endpoint/connector vendor’s requirements when a preset differs from your design.

## CLI and report assignments

Generate separate route JSON reports with the existing `wayricad-si screen ... --output route.json` command. A suite consumes Quick SI `wayricad.quick-si/v1` reports, not standalone eye output or a previous suite report.

Prefer adding `--role P --group lane0` to `screen` when generating the first route and `--role N --group lane0` for its mate. Alternatively add only these two top-level assignment fields to **copies** of existing route reports:

```json
{
  "suite_role": "P",
  "suite_group": "lane0"
}
```

This fragment shows fields to add; it is not a complete route report. Preserve the existing `schema`, `path`, measurements, assumptions, status, `board` and `board_sha256`. Assign the other independently screened lane report `N` with the same group. For a bus use `clock`/`data`. Role matching is case-insensitive; group names must match exactly.

```console
wayricad-si profiles
wayricad-si suite --profile pcie-gen3 --reports tx-p.json tx-n.json --max-delay-ns 1 --max-skew-ps 5 --max-impedance-error-percent 10 --max-delay-to-rise-ratio 0.2 --output suite.json --html suite.html
```

The four values above are arbitrary command examples, **not PCIe limits**. Choose separate output filenames so your original evidence remains available. Differential impedance will remain unknown: two independent single-ended route calculations are not a coupled differential extraction, even when an impedance budget is supplied.

`profiles` and `suite` run in ordinary Python without KiCad or network access. Suite exit codes are 0 for within-budget, 1 for an input/export error, 2 for blocked, and 3 for review/incomplete. A suite accepts up to 64 route reports (16 MiB per file). Unknown evidence remains visible in both HTML and JSON.

## Python API

```python
from signal_integrity_advisor_plugin.protocol_profiles import list_profiles, get_profile
from signal_integrity_advisor_plugin.protocol_suite import screen_suite

profiles = list_profiles()
profile = get_profile("spi")
result = screen_suite("spi", reviewed_route_reports,
                      budgets={"max_delay_ns": 1.0, "max_skew_ps": 20.0})
```

`reviewed_route_reports` is a list of full route-report dictionaries with assignments. The budget keys are `max_delay_ns`, `max_skew_ps`, `max_impedance_error_percent` and `max_delay_to_rise_ratio`. Unknown keys and invalid numeric budgets raise `ValueError`. The result schema is `wayricad.protocol-suite/v1`, with profile information, route count, budgets, individual checks, overall status and limitations. The pure screening API does not reopen the board or verify that files still match their stored hashes; the caller must enforce revision freshness.

## Interpret results

- **BLOCKED:** unusable input, duplicate route, incompatible saved revisions or unspecified M.2 interface.
- **REVIEW:** an evaluated user budget is exceeded, or an illustrative eye rate needs review.
- **INCOMPLETE:** evidence, assignments or a needed budget is missing.
- **WITHIN_BUDGET:** only the evaluated quantities meet the supplied limits; never standards compliance.

Reference-layer/net coverage records geometric evidence, not solved return-current continuity. Vias and layer changes need return-path review. No IBIS driver, coupled crosstalk, channel loss, receiver model, compliance mask, memory training or ODT simulation is performed.

Bit/transfer rate does not determine driver edge bandwidth. Where applicable, the catalog reports half the NRZ symbol rate as an informational Nyquist frequency; this is not a simulated channel bandwidth. I2C, CAN and legacy PCI do not receive an NRZ Nyquist interpretation. DDR/RGMII alternating-pattern frequency likewise does not replace actual rise-time information. Matching the optional PRBS7 eye rate to a preset validates neither encoding nor receiver margin.
