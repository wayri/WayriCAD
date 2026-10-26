# WayriCAD 3.6.32 release validation

This release adds finer computed thermal playback and reviewed native KiCad IBIS
circuit exports. [Methods, assumptions and Marble evidence](IBIS_CIRCUIT_EXPORT_2026-10-26.md)
distinguish structural integration, synthetic simulation and physical limits.

Source checks use Windows/Python 3.14.2. Native checks use KiCad 10.0.6,
Python 3.11.5 and wxPython 4.2.2. The SI suite passed 159 tests, with 10 skips
and 101 subtests. Missing model roles, changed source/model files, bad topology,
unknown copper, via assumptions, staging rollback, all-case output and distinct
export namespaces are checked. Native IBIS controls and thermal Previous/Next
were exercised using synthetic data; original user boards were not edited.

The initial shared run found the newly added copper provenance field was not
synchronized to canonical RLC. Both independent engines now match byte-for-byte;
the focused ten shared-engine tests passed. An initial full thermal run failed
in native SciPy/OpenBLAS under machine memory pressure; this is not counted as
a pass. Follow-up bounded-thread and CI results are recorded below once complete.

Exact-source CI, package validation, isolated ZIP/wheel checks and public
asset/hash verification are release gates. The public feed remains on the prior
release until new assets pass download verification. Existing versions and
binaries remain unchanged.

## Local package checks

With BLAS/OMP thread counts bounded to one for the validation process, the full
thermal suite passed 256 tests, with 28 skips and 196 subtests. The native ZIP
checks use copied external tests, not tests shipped as plugin payload.
The frozen Quick SI ZIP passed 38 core and five native GUI tests in independent
isolated KiCad Python processes, with zero skips and normal exits. Production
module bytes matched both ZIP and frozen source; loaded plugin/runtime paths
were restricted to the extracted package. No sibling checkout imports supplied
missing implementation. Native clipboard parser limits and library-registration
warnings are documented in the method audit.

The QuickTherm ZIP passed 31 focused numerical tests in isolated native Python,
and native Previous/Next, slider and playback controls over a precomputed
101-frame result. All 23 loaded production/runtime modules matched ZIP bytes;
original and staged fixture hashes remained unchanged. The final process exited
cleanly. This final isolated run did not recompute the complete board fixture;
source native checks and the extracted solver's numerical tests are distinct.

The final local shared suite passed 613 tests, with 123 skips and 464 subtests.
All 26 built archives passed the private-path/cache scan (5,849 members), and
1,277 tracked source-archive members matched the checkout exactly. The isolated
wheel passed CLI, report-asset and local-server checks. An isolated source-build
dependency install hit MemoryError; the installed setuptools backend rebuilt
the final source archive successfully without changing production code.

Initial CI identified a macOS-only test expectation: temporary paths may resolve
from `/var` to `/private/var`. The test now compares canonical paths, matching
the implementation's existing config-relative resolution contract. This changes
only the test expectation; model path resolution is unchanged. A new exact-source
CI run is required before publication.
