# WayriCAD 3.6.1 release notes

Trace RLC and Quick SI now include corrected EMerge-derived transmission-line estimates. The saved-board analyzer estimates microstrip and symmetric stripline impedance only when the stackup and reference copper support those geometries. A new manual cross-section view calculates CPW, grounded CPW and edge-coupled symmetric stripline from dimensions entered by the user. The preview shows the assumed conductors and return planes.

Unsupported board geometry, missing reference copper and mixed routes remain explicitly unresolved; the tools do not claim protocol compliance or a single impedance for a route that changes cross section. The [capability matrix](audits/RLC_EMERGE_CAPABILITY_MATRIX.md) records the numerical references, assumptions and remaining limits.

BOM Studio also completes its local Quit HTTP response before stopping the server, and its asynchronous preview regression waits for a measured deadline on slower CI hosts.

Validation for this release includes focused numerical references, KiCad 10 native-Python geometry tests, the repository and plugin test suites, independent PCM archive checks, wheel import smoke tests and multi-platform CI. Native launch and analysis were checked on Windows with KiCad 10.0.6; the other CI operating systems validate source and package behavior, not a running editor.
