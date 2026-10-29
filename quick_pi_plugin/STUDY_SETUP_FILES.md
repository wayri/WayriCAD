# Save and recall a Quick PI study

Every saved-board **AC / SMPS**, **Multi-net DC**, **Electrothermal**,
**Transient load steps** and **PDN target / capacitor bank** dialog has
**Save setup…** and **Load setup…** alongside its saved-result actions.

1. Open the study from the current PCB's Quick PI window and edit its inputs.
2. Choose **Save setup…**. The file chooser starts beside that PCB and proposes
   `<board>.quick-pi.<study-mode>.setup.json`. Choose another name or folder if
   desired. Each study mode has its own suggested name.
3. Reopen that same study type and choose **Load setup…**. Wrong-mode files are
   rejected before changing any inputs. A changed board revision needs explicit
   review; a multi-net study also checks its saved net and pad assignments against
   the available board inventory.
4. Review the restored inputs and run a new analysis. Loading setup clears the
   old results, because those results were computed for different inputs.

| Study | Retained inputs |
|---|---|
| AC / SMPS | Quick/custom mode, quick recipe and dimensions, all custom conductors, RMS harmonics, copper temperature, mesh and solver settings |
| Multi-net DC | Complete case JSON, grouped sources/loads, explicit shared returns, per-case thermal and mesh settings |
| Electrothermal | Steady/transient mode and the complete model, material-library selections, thermal mappings, cooling and coupling inputs |
| PI transient | Both quick and advanced input tables, selected mode, explicit R/L/C, individual shunt C/ESR/ESL banks and load rise times |
| PDN impedance | Source R/L, ripple and current-step target, frequency range, sample count and each capacitor type's C/ESR/ESL/quantity |

Blank draft table entries remain blank rather than being replaced with assumed
physical values. They still need correction before the solver can run. The
steady-feedback editor does not accept a transient electrothermal setup.

**Load simulation…** is separate: it opens the completed numerical result in a
read-only viewer without running or replacing editable setup. **Save setup…**
does not save solver results. Neither operation writes the PCB, its routing,
footprints, zones or schematic.

The older **Load/Save study JSON**, **Load/Save inputs JSON** and **Load/Save model
JSON** actions remain for exchanging raw solver models with CLI workflows. Their
chooser also starts in the PCB folder when launched from Quick PI. Those raw
models are not interchangeable with the versioned setup envelopes. HTML/PDF
reports remain presentation exports rather than setup files.

[Main Quick PI guide](USER_GUIDE.md) ·
[Simulation file format and source binding](../docs/PROJECT_RESULTS.md)
