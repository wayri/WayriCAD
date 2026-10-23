# WayriCAD 3.6.28

This release adds guarded via stitching, a clearer Fanout workflow and shared
responsiveness improvements. It also includes the first downloadable WayriCAD
Assistant package, marked **testing**. All 24 independent PCM ZIPs, a Python
wheel and a source archive are attached.

| Change | What to expect |
|---|---|
| Guard via stitching | Follow selected signal nets or captured tracks using a separate guard net. Set pitch, offset and one/both sides; inspect accepted and rejected through-vias before Apply. |
| Guided Fanout | Choose targets, choose a style, then review actual component thumbnails and Before/After geometry. Planning is cancellable; primary actions remain accessible in small windows. |
| Responsive routing previews | Planning runs in an isolated native process against a private snapshot. Save edits before fast preview; live native capture remains an explicit, slower option. |
| Faster shared interaction | Cached dropdown metrics, batched drawing and indexed exact picking remove repeated full-board work. |
| Faster Quick PI startup | Removes duplicate geometry extraction and batches inventory updates. Marble geometry-ready time: 33.09 s to 20.26 s. |
| Quick SI/RLC startup | Defers the exact numerical backend until needed. This reduces setup imports but moves initialization cost to the first calculation; formulas are unchanged. |
| QuickTherm selection | Corrected selected component labels and duplicate stationary-hover annotations; batched inventory population. |
| WayriCAD Assistant — testing | Local fuzzy matching turns supported requests into reviewed CLI plans, asks for missing inputs and opens reports. It is not a general language model and does not automatically apply layout changes. |
| Safer reviewed writes | Source identities include keepouts, pad geometry, vias, board cuts and live manufacturing floors. CLI routing copies preserve project/custom-rule companions and refuse occupied output paths. |

On Marble, subsequent selected-net redraw fell from 544 ms to 8.21 ms. Fanout
submission returned in 22–55 ms rather than blocking the window for 8–9 s;
the complete isolated preview still took 9–14 s. These measurements have
different scopes and are not a guarantee for every board or weaker hardware.
Dense-board first loads remain substantial.

The connected two-plane guard fixture accepted 22 vias with no new native DRC
findings after refill. A single-plane fixture produced dangling-via warnings;
filled copper on one layer does not establish a useful through-via connection
or RF shielding. Tested Marble clock routes had zero legal guard sites under
their existing rules. Arc targets are unsupported, not replaced by chords.

Refresh the WayriCAD repository in KiCad Plugin and Content Manager, install
updates, then restart PCB Editor. The 18 IPC packages advance to 3.6.28. Six
unchanged native packages retain their existing versions and bytes.

Evidence and limitations:

- [Performance measurements and validation](audits/SUITE_RESPONSIVENESS_2026-10-23.md)
- [Assistant implementation and scope](audits/assistant-local-orchestration.md)
- [Release packaging checks](audits/RELEASE_3.6.28.md)

Native checks use Windows, KiCad 10.0.6 and Python 3.11.5. Standalone windows,
saved-board validation and portable CI do not qualify every connected-editor
IPC workflow or operating system. No private boards or validation caches are
included in the release.
