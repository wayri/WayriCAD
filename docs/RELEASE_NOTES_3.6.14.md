# WayriCAD 3.6.14

Quick PI and QuickTherm now support explicit lead, solder and BGA contact paths.
QuickTherm's setup inputs fit the visible sidebar, including expanded sections
and long mapped field names. All 17 IPC packages advance to 3.6.14 because they
vendor the shared runtime. Fusion 0.9.8 and Variant Manager 0.6.1 retain their
existing published package bytes and download locations. The suite still has
19 independently installable plugins.

## Changes

- Native contact editors accept saved pad faces, reviewed material properties,
  dimensions and provenance. Ordered segments are in series; separate paths are
  in parallel. Cylinder, rectangular lead and truncated spherical ball shapes
  have analytical axial electrical/thermal resistance.
- Quick PI 2.5D constant-current DC solves current sharing through package
  contacts, retains finite pad/barrel conduction and reports contact I²R heat
  separately from planar and barrel copper losses. Missing/ambiguous pads,
  conflicting ownership, cross-net electrical contacts and oversized necks reject.
- QuickTherm multilayer steady/transient studies connect explicit body/junction
  nodes to saved pad copper faces and solve signed heat sharing. Physical paths
  replace aggregate RC resistance and single-pad proxies. Component heating R/C
  setup is available beside the contact editor for steady as well as transient
  studies.
- Source-bound PI report import checks pad identities, geometry, properties and
  I²R consistency. Series-segment heat is distributed conservatively between
  package and board using thermal-resistance coordinates. Component dissipation
  remains a separate input, entered once.
- QuickTherm form inputs use available width, headings span their own rows,
  labels wrap and compact buttons preserve their explicit sizes. Native checks
  expand the sections at three window sizes and test long field names.
- README screenshots and offline help describe the current controls, conduction
  inputs and supported modes.

## Verification and limits

Windows / KiCad 10.0.6 / Python 3.11.5 native checks cover the actual saved-board
PI mesh/solve, exported report transfer, multilayer steady and 21-frame transient,
both modal contact editors and source immutability. Six native UI tests cover
resizing, editing, asynchronous execution, probes and close. Numerical tests use
analytical resistances, independent ball quadrature, RC response, current/heat
sharing and conservation. Isolated PCM and wheel checks exercise installed
payloads without source-plugin paths. See the [acceptance record](audits/PACKAGE_CONDUCTION.md)
and [inputs, equations and limits](PACKAGE_CONDUCTION.md).

Contacts are constant-property, massless one-dimensional axial elements. Internal
component/joint gradients, constriction/wetting defects, joint heat storage and
temperature-dependent contact feedback are unresolved. STEP models provide
geometry and display one declared component-node temperature; they do not infer
alloy, conductivity or connectivity. Imported loss playback uses a fixed
electrical operating point. These contacts are currently unsupported in Quick
PI's 3D, resistive-load, series, rail transient and electrothermal feedback modes.
Materials, boundary conditions and space/time refinement still require review.
This release does not establish native compatibility on other KiCad versions or
operating systems; portable CI and native Windows tests provide separate evidence.
