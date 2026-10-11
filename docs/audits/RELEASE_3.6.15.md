# WayriCAD 3.6.15 release validation

Prepared from current develop in an isolated release checkout. Unrelated dirty
source work was preserved. No existing release binaries were replaced.

## Checks

Windows, Python 3.14 portable test runtime:

| Suite | Passed | Skipped | Subtests passed |
|---|---:|---:|---:|
| Shared/runtime/source regressions | 419 | 73 | 164 |
| Quick PI portable tests, excluding separate production mesher suite | 218 | 25 | 186 |
| Quick SI | 60 | 3 | 63 |
| QuickTherm | 226 | 24 | 190 |
| Constraint Studio | 372 | 0 | 0 |

Two added offline thermal gesture tests execute the JavaScript handlers with
Node. Six PI/SI native checks and five QuickTherm native checks pass using KiCad
10 native Python with clean process exit. The thermal test fixture is created
in a separate bounded pcbnew worker, matching standalone plugin ownership.

Official PCM schemas, payload Python syntax, independent runtime payloads,
icons, entrypoints and SHA-256 checks pass for all 19 packages. Wheel and source
distribution build successfully. Current documentation and bundled PCM images
validate. Release text payloads have no known private machine paths.

## Limits

Skipped native/dependency tests are not passes. These checks do not establish
native compatibility on every OS/KiCad version, physical thermal accuracy,
CFD/enclosure heating, or a speed comparison with Fang. Browser pixel inspection
of every report was not repeated; offline event behavior is tested numerically.
Fusion 0.9.8 and Variant Manager 0.6.1 retain published package bytes and hashes.
CI and final public download checks are required before release promotion.
