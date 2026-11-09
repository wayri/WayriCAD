# Third-party notices

The owner-authored KiCad WebView software is MPL-2.0. Matching preferred source for this release: https://github.com/wayri/kicad-webview/tree/v0.1.0-beta.2. Preserve LICENSE and these notices when distributing builds. Historical extraction records are in SOURCE-PROVENANCE.json; current source is maintained in this repository.

| Component | License / notice | Scope |
| --- | --- | --- |
| Three.js 0.171.0 | MIT; [THREE-LICENSE](engine/vendor/THREE-LICENSE) | Included in the 3D runtime; original authors' credits retained |
| fzstd 0.1.1 | MIT; [LICENSE](engine/vendor/fzstd/LICENSE) | Included decompression code; Arjun Barrett's credit retained |
| Owner-provided SPIKE geometry subset | MPL-2.0 for this supplied subset; [notice](engine/vendor/SPIKE-ENGINE-NOTICE.md) | Original provenance remains; other SPIKE software is not relicensed |
| Atlassian Forge SDK and transitive packages | Their supplied licenses and Atlassian Developer Terms | Optional Confluence integration only; its build retains per-package notices in static/licenses and FORGE-DEPENDENCY-NOTICES.md |
| iframe-resizer 4.4.5 | Upstream MIT package declaration and [retained provenance](integrations/confluence/licenses/iframe-resizer-4.4.5/PROVENANCE.json) | Optional Forge controller dependency; the upstream package omitted license text, and supplemental 4.4.4 MIT text is labelled accordingly |

The OCCT STEP decoder/runtime, PDF.js, KiCanvas and host applications are not bundled. The optional Altium adapter loads an external service only on explicit request; it does not bundle or relicense Altium software. Demo design data has separate provenance and is not covered by the software's MPL grant.
