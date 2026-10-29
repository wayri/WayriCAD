# Post-solve insulation engineering screen

Run a multi-net DC study first, then open **Spacing screen…**. This read-only
screen compares two or more completed distinct single-net results from the same
saved-PCB SHA-256. It neither edits the PCB nor certifies insulation safety.

Enter a specific rule/clause citation, material/surface assumptions, environment
(including relevant pollution, altitude and coating assumptions), minimum planar
clearance and creepage in millimetres, and the rule's applicable voltage limit.
No standards table, material group or threshold is guessed.

Review one voltage assumption:

- **Common domain:** give a common-reference description and an explicit offset
  in volts for every screened net. The screen adds these offsets to each solved
  potential envelope, then uses the largest separation of envelope endpoints.
- **Conservative envelope:** supply your reviewed maximum voltage difference
  and its evidence/citation, including relevant operating/transient bounds.
  Independently solved rails do not establish a common absolute reference.

The table measures minimum Euclidean distance between the actual extracted
same-layer copper polygons, including their holes. It reports both the polygon
gap and a conservative lower bound that subtracts both declared curve
tolerances. Missing tolerance, invalid/incomplete polygons, unknown potential
samples and absent common layers remain **UNKNOWN**. Closest-point markers
refer to extracted polygons. **Locate selected net pair on PCB** uses the
originating editor and rejects a changed saved PCB; it selects the named nets.

A straight polygon gap is **not physical creepage**. Creepage stays **UNKNOWN**
unless you provide a reviewed surface measurement/path for that net pair,
including slots and obstacles. Optional measurements are entered as JSON:

```json
[
  {
    "net_a": "VIN",
    "net_b": "GND",
    "length_mm": 5.2,
    "evidence": "Reviewed surface path drawing A-B, including slot and obstacle boundaries",
    "reviewed": true
  }
]
```

**SCREENED** means the supplied evidence meets your entered limits within this
model. **REVIEW_REQUIRED** means a lower bound or reviewed surface measurement
falls below a limit. **UNKNOWN** means evidence/applicability is incomplete;
failed batch cases are listed and prevent an overall SCREENED result. Exceeding
the declared voltage applicability limit produces UNKNOWN, never acceptance.
No result covers inter-layer/3D air paths, board thickness, unscreened nets,
coatings, transient electric fields, dielectric breakdown or compliance testing.
The screen is bounded to 32 cases, 4,096 polygons and 200,000 vertices per net,
and 2,000,000 potential samples per net. Invalid polygons are not repaired.

## JSON API

`quick_pi_plugin.insulation_screen.screen(batch_bundle, policy)` returns a
strict-JSON-compatible report containing `status`, `source_sha256`, `policy`,
`pairs`, `potential_envelopes_V`, `excluded_cases` and `notice`. Each pair has
clearance/creepage statuses, measured/lower-bound distances, maximum reviewed
voltage separation, closest points in millimetres, layer ID and evidence issues.
A policy example (numbers illustrate the format, not an engineering rule):

```json
{
  "schema": "wayricad.pi-insulation-screen/v1",
  "rule_citation": "Project rule document, reviewed clause",
  "material": "Explicit laminate and surface assumptions",
  "environment": "Explicit pollution, altitude and coating assumptions",
  "minimum_clearance_mm": 2.0,
  "minimum_creepage_mm": 4.0,
  "voltage_limit_V": 50.0,
  "voltage_reference": {
    "mode": "conservative-envelope",
    "reviewed": true,
    "maximum_voltage_difference_V": 25.0,
    "citation": "Reviewed worst-case voltage-envelope calculation"
  },
  "reviewed_creepage": []
}
```

The alternate reference object is
`{"mode":"common-domain","reviewed":true,"domain":"Reviewed DC reference","net_offsets_V":{"VIN":0,"GND":0}}`.
Offsets must be supplied for every screened net. Source fingerprints are retained;
no new fingerprint can make historical results current.

## Command line

```text
wayricad-pi --insulation-result pi-cases.json --insulation-policy insulation-policy.json --output spacing-screen.json
```

Only completed multi-net results are accepted. Exit 0 means SCREENED against the
entered evidence; exit 3 reports unknowns or findings; exit 2 reports invalid
inputs. This workflow does not run a new simulation or alter the saved board.
