# WayriCAD 3.6.20 validation

## Scope

UI sizing, scrolling, table reading and offline help across 23 independently installable plugins. No new numerical solver claims are introduced. Board preview, explicit apply, source freshness and undo contracts remain in place.

## Local evidence

Windows; KiCad 10.0.6 bundled Python 3.11 and wxPython. Native frame tests use 1024×720 windows with actual control geometry and sash movement.

- Shared layout regressions: 7 passed, including complete 1800-character native table values, supplementary Unicode values, reader search/resizing, expanding scrolled content, idempotent setup, destroyed dropdown callback and grid values.
- Fanout, Via Stitching, Heater Designer, Copper Balancer and Planar Magnetics: actual window construction and live settings divider movement passed.
- Quick PI, QuickTherm, Quick SI and Trace RLC: 6 native checks passed, including existing viewport/sidebar preservation checks; additional resize harness exercised 7 sashes and 4 scroll areas.
- Fusion, Variant Manager, Component Arranger, Trace Refiner, Silkscreen Labels and Layer Counter: 40 native tests passed. A six-window harness checked construction, resizing and expanded content.
- New screenshots: Component Arranger and Trace Refiner help-layout.png, captured from native windows at 1024×720; existing workflow screenshots retained. Captures contain only generic fixture data.
- Offline help coverage: 23 bundled guides checked for navigation, local images and independent package dependencies.

- Root portable suite: 475 passed, 89 skipped, 222 subtests passed. Skips include unavailable native bindings.
- Analytics/BOM suite: 1,272 tests run, 2 skipped, process exit 0; 7 focused HTTP tests passed. Local help HTML, extracted CSS, images, guide text, MIME/CSP and route boundaries checked.
- Actual WebView2 rendering at 1024×720: Analytics grid and Constraint scope/worksheet/map areas resized to 480 px; horizontal/vertical scrolling and real dialog action visibility passed. These are DOM geometry checks, not pixel appearance checks.
- Official KiCad schemas, independent PCM payloads, entrypoints, icons, documentation images and ZIP hashes passed validation.

Exact-source GitHub CI and public asset verification are release gates; their final identifiers are recorded with publication.

## Limits

Native Linux/macOS windows, every display scaling factor, and every live-editor workflow were not exercised. Some earlier combined helper processes hung after assertions during teardown and were terminated; those runs are not clean-exit evidence. The shared seven-test/five-window harness and individual native plugin tests exited normally. Portable tests that skip native bindings are not native passes.
