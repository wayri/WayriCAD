# Automatic layer routing profiles

Constraint Studio saves named protocol instances, native KiCad 10 tuning profiles
and per-layer custom rules. Once applied and reloaded, KiCad owns the routing behavior. Studio need
not remain open. This is persistent setup, not a background routing hook.

## Setup and routing

1. Configure and save the actual physical stackup in KiCad Board Setup.
2. Create a named instance such as CAN1, CAN2, Ethernet1 TX or DDR1 Data. Each
   saved instance has its own tab; switch tabs to review its nets and dimensions. Select
   its protocol family and exact nets using checkboxes, search and Select visible.
   One net or a group is supported. Existing-netclass scope remains available.
   Differential routing requires
   KiCad-recognized pair naming; a protocol label alone does not establish a pair.
3. Open **Layer routing profiles** in Studio. Select the instance's signal type,
   target impedance and geometry tolerance. Add each permitted signal layer.
4. Select the actual continuous reference plane(s). Outer layers commonly use one;
   internal layers commonly use references above and below. Verified values can
   use other valid stackups, including one-sided internal references. Enter
   fabricator/field-solver width and gap values, or estimate a width while
   keeping the pair gap fixed where the approximation supports the geometry.
   The per-layer preview shows vertical trace/pair copper at a common scale;
   Trace, Pair and Trace + pair modes update as dimensions are edited.
5. Review reference-plane continuity and layer-transition return paths, then
   stage and export. Close the source project before applying the review with
   its bundled Apply Review utility. Reopen the project in KiCad.
6. Use KiCad's **netclass/rule-driven sizing** for tracks and differential pairs.
   Width and gap then update on routing layer changes, without selecting a new
   size each time. A manually selected explicit size can override the defaults.

Existing copper is not automatically resized. Existing higher-priority scoped
rules can override the profile, including local BGA neckdowns. Generated rules
are inserted above unconditional board defaults and below existing scoped
routing exceptions. Review unusual ordering in the worksheet. Optionally
prohibit tracks on layers without a profile row; vias are not prohibited by that
policy.

## Multiple protocols and net groups

Each instance owns independent layer geometry and an exact saved net list.
Multiple CAN buses, Ethernet ports and DDR groups can coexist. Protocol family
is an organizational label, not an automatic electrical specification. DDR data,
address/control, clock and strobes can require separate single-ended or
differential groups with different targets; this page does not certify DDR timing.

The filter is a selection aid, not a wildcard assignment: newly added nets are
not silently included. Missing/renamed members are flagged. Both members of
recognized `_P`/`_N` or `+`/`-` pairs must be selected. Other net names still need
KiCad-recognized pairing before native differential routing is possible.

Exact-net mode generates native `A.NetName` conditions and leaves all netclass
assignments unchanged. Those rules supply the router's per-layer optimal width
and gap; the saved native profile is a geometry reference, not an assigned
netclass profile in this mode. Netclass mode assigns the native profile as before.
Duplicate explicit memberships and overlaps with tuning-profile netclasses
visible in saved assignments/patterns are rejected. Schematic-only membership
and arbitrary hand-authored rule overlaps still require native review.

Use **Duplicate** to reuse geometry for a different instance; its net selection
starts empty. **Edit instance** changes its membership and dimensions. **Remove**
stages removal of only that instance's managed rules/profile; undo is available.
Independent edits to owned rules/profiles block regeneration or removal.

## Calculation and review limits

The built-in width estimate uses closed-form screening approximations for
homogeneous microstrip and symmetric stripline, including copper thickness and
fixed-gap differential coupling. It rejects mixed dielectrics, composite
sublayers, asymmetric stripline, intervening copper and dimensions outside its
screening range. Verified external dimensions may be entered for asymmetric or
mixed-dielectric cross-sections with supported stackup representation.
The native profile accepts manually verified dimensions for any distinct signal
and reference copper layers in the saved stackup, including intervening copper
and one-sided internal references. The approximation still rejects unsupported
cross-sections; the preview is a geometry illustration, not an impedance solver.

The estimate excludes mask, roughness, weave, dispersion, plane voids and via
discontinuities. It is not a field-solver or fabricator sign-off. Geometry
tolerance is **not impedance tolerance**. Time-domain tuning is deliberately
disabled; zero delay fields are unused and do not claim zero physical delay.

Studio fingerprints the complete saved stackup. Changed stackups produce a
stale-profile error on reopening/review; recalculate and explicitly restage.
Studio cannot invalidate native settings while it is closed. It also detects
independent edits to managed native profiles, generated rules and assignments.
Unmanaged profiles, project fields and unrelated rules are preserved. Updates
share Studio's undo, revision checks, review diff and offline apply workflow.

## Native validation and design references

Implementation follows the KiCad 10 `common/project/tuning_profiles.cpp`
serializer: profile widths/gaps are integer nanometres, netclass assignment is
`tuning_profile`, and time-domain tuning is disabled. KiCad's
`ROUTER_TOOL::updateSizesAfterRouterEvent` re-evaluates width and gap for the
destination layer. Manual sizing modes remain native overrides.

- [KiCad 10 tuning profiles](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#tuning-profiles)
- [KiCad native profile serializer](https://github.com/KiCad/kicad/blob/10.0/common/project/tuning_profiles.cpp)
- [KiCad router layer-change implementation](https://github.com/KiCad/kicad/blob/10.0/pcbnew/router/router_tool.cpp)
- [Altium controlled-impedance routing](https://www.altium.com/documentation/altium-designer/pcb/high-speed-design/interactively-routing-controlled-impedance): inspiration for reference-linked, per-layer geometry.
- [Siemens Xpedition constraint management](https://blogs.sw.siemens.com/xcelerator-academy/2023/03/27/how-to-master-the-game-of-setting-rules-constraint-manager/): inspiration for net/layer constraint tables and central review.

Development validation includes backend persistence/staleness/ownership tests,
real native WebView calculate/stage/undo, native KiCad 10.0.5 DRC acceptance of
different widths and gaps on two layers, and a native project load/save
round-trip. The native DRC fixture is deliberately violating, not a clean board.
Interactive routing transitions were verified in official native source;
an end-to-end mouse-driven route/via test has not been performed.

Native acceptance uncovered an imported numeric-format defect: bare `.2mm`
constraint values are rejected by KiCad's rule lexer. Export now normalizes
those numeric tokens to `0.2mm`, preserving comments and unrelated syntax.
This repair appears in the review diff; source files are not edited on load.
