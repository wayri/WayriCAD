# HTML and PDF reports

Use the tool's normal HTML export for its board views, probes and detailed plots.
Quick PI, Quick SI, QuickTherm, their transient studies and Analytics Studio share
summary styling, section links, readable tables and print rules. Section links and
the numerical content work without JavaScript. JavaScript adds table filtering,
sorting and the existing interactive viewers; no CDN is required.
Raw JSON blocks stay in closed evidence disclosures, rather than appearing in the
normal report view. Paired exports include a complete JSON download.

## Save a PDF

Open a trusted exported HTML report and choose **Print / save as PDF**, or use your
browser's print command. Check its print preview: interactive canvas content depends
on the browser's current rendered state. Retain the HTML and paired JSON for probes,
3D interaction and complete numerical evidence.

For direct, browser-free PDF export, install the optional renderer in the Python
interpreter running the command:

```text
python -m pip install "wayricad[reports]"
python -m wayricad_runtime.tool_cli report-pdf review.html --output review.pdf --evidence review.json
```

`--evidence` is optional. When provided, declared board/study fingerprints are
checked before and after rendering. The exporter protects its HTML, evidence and
declared source files from being overwritten, including hardlink aliases. Failed
rendering retains an existing PDF.

The direct exporter produces paginated A4 text, tables and embedded PNG/JPEG
figures. Wide tables continue in column panels with the identifier column repeated;
long tables repeat headers. It never executes JavaScript or loads external files or
URLs. Canvas, SVG, external images and other unsupported views are explicitly
listed in the PDF as views retained in HTML. Merged table layouts are flattened
with a notice. This static PDF is an evidence companion, not a replacement for an
interactive board report.

Quick PI also saves differential probe selections and their result table in its
HTML/JSON report. A saved A/B reading remains printable in PDF even when the
interactive canvas itself is unavailable. Probes compare points inside one solved
2.5D DC reference; they do not subtract unrelated case results or infer 3D barrel
interior voltages.

JSON blocks are summarized with their text fingerprint in a normal PDF. Add
`--include-raw-evidence` to `report-pdf` only when you want the complete JSON
appendix printed. Numerical result tables remain visible in either mode.

## Reports from any tool's JSON

Tools that only export structured JSON, including RLC results, can use the common
report reader:

```text
python -m wayricad_runtime.tool_cli report result.json --html review.html --pdf review.pdf --title "Board review"
```

This renders the recorded values in semantic tables without recomputing or
reclassifying the analysis. Unknown values stay unknown; missing columns are marked
as not supplied. The input file's SHA-256 identifies the saved result. Nested
objects remain separate sections. The input is limited to 16 MiB, 20 nesting levels
and 20,000 values; use the originating tool's exporter for large time-series or
field datasets. Both requested formats are prepared before publication and restored
if publication fails. Source designs and inputs remain protected.

## SI delay and phase

In Quick SI's protocol suite, assign each routed leg a **P** or **N** role and the
same pair group. Review the source-to-receiver direction, enter an explicit phase
frequency and choose a reference pair if comparing lanes. The report includes leg
delay, signed and absolute intra-pair skew, unwrapped/wrapped propagation phase and
inter-pair mean-delay comparisons. See the Quick SI guide for formulas and coverage.

These are independent route propagation estimates. They do not establish coupled
differential propagation, receiver crossing time or protocol compliance. Device,
package and discontinuity delays remain outside this comparison. Missing delay or
revision evidence remains unknown instead of becoming a zero mismatch.
