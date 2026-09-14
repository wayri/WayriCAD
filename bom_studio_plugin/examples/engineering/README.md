# Engineering examples

All part, stock and geometry examples here are synthetic. They do not establish electrical/physical compatibility or actual availability. No reviewer credentials are included.

`bom-variant-*.json`: pass to `bomvariant preview --request`; review the generated plan, then `bomvariant apply --confirm VARIANT`. Names must not already exist.

`new-catalog-part.json`: schema guide for `catalog edit-preview --request`; it deliberately uses a fictional manufacturer/MPN. Change it before curating real parts.

`build-scenario.json`: current project, two variants; it deliberately has no invented offers. Missing stock will appear as gaps. Check that the named variants exist in your project.

`review-policy.json`: local engineering approval + BOM errors, not a complete qualification policy. It does not secretly require stock or land-pattern coverage.

`land-pattern-synthetic.json` and `synthetic.pretty/`: a declared specification that matches the synthetic demo resistor footprint. This is an interface/geometry test, not a manufacturer recommended land pattern.

Run `TRY_ENGINEERING_SAMPLE_WINDOWS.bat` or `python cli.py gui --engineering-demo` for a fresh temporary project/catalog. The sample contains explicitly fictional low-stock/NRND observations, no accounts, one independent variant and a synthetic footprint. It does not contact the example source URLs.
