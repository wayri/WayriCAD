# Primary sources used for version 0.6

Accessed 9 September 2026. These references informed bounded adapters and mass proxies, not a native-host certification. Links are recorded for provenance; the runtime does not fetch them automatically.

* KiCad 10 CLI: https://docs.kicad.org/10.0/en/cli/cli.html — native command families and jobset run.
* KiCad 10 Manager/job sets: https://docs.kicad.org/10.0/en/kicad/kicad.html — Execute Command and JOBSET_OUTPUT_WORK_PATH.
* KiCad official Linux downloads: https://www.kicad.org/download/linux/ — real host-download route checked; installation was not successful in this environment.
* Murata MLCC FAQ: https://www.murata.com/en-global/support/faqs/capacitor/ceramiccapacitor/conf/0004 — product/series mass is typical, production-lot variation exists; mass belongs to the specific construction.
* Murata linked mass table: https://www.murata.com/-/media/webrenewal/support/faqs/products/capacitor/ceramiccapacitor/weight_table.ashx?cvid=20250127061156000000&la=en — visually checked table; different dielectric/thickness options remain separate in suggestions.
* Vishay TR series document: https://www.vishay.com/doc/?20023= — visually checked page 1 weights, document dated 8 August 2022, explicitly EOL December 2022. Historical mass proxies only; not recommended current procurement parts.
* Nexperia MMBT2222A material content: https://www.nexperia.com/chemical-content/MMBT2222A.html — representative SOT23 transistor mass, specific orderable record, indicative material content.
* Nexperia BAS416 material content: https://www.nexperia.com/chemical-content/BAS416.html — representative SOD323 diode mass.
* Nexperia NGD31251D material content: https://www.nexperia.com/chemical-content/NGD31251D.html?identifier=NGD31251D — representative SO8/SOT96-2 IC mass.

Nexperia records are manufacturer-indicative material declarations, not guarantees for every device in a named package. Seed suggestions retain their proxy basis and source; no manufacturer PDFs are reproduced or bundled. See masslib.py for the actual small supported seed set. The synthetic qualification example is deliberately not derived from a manufacturer design.

Prior official API/format/supplier references remain in RESEARCH_SOURCES.md for the features of earlier releases.
