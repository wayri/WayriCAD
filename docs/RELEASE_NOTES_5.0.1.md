# WayriCAD 5.0.1

- WayriCAD Assistant recommends same-net pad groups, keeps prior simulation
  settings during follow-ups, and displays local reports in an embedded
  viewer. Its PCM package includes the providers required by isolated
  analysis workers.
- Quick PI transient reviews show conservation checks and half-step voltage
  and current changes beside the simulated limits.
- Quick PI two-port results explain which port supplies current and which port
  measures voltage.
- Trace RLC exports identify missing circuit parameters and their extraction
  blockers before handoff to a transient or impedance model.

- Quick PI runs steady Joule heating from the main **Run** button in 2.5D
  and 3D. The 3D path accepts an equipotential source pad group and independent
  current loads, each with its own pad group. The 3D field and report include
  copper temperatures and cold-to-heated comparisons.
- Solved power trees overlay voltage, current, input and output power, and
  modeled loss on reviewed stages and loads. Shared copper loss appears once.
- Quick PI, Quick SI and Trace RLC can rerun supported paths in the background
  after their watched nets change in the originating KiCad editor.
- The standalone [Marble Zxx demonstration](../quick_pi_plugin/examples/marble_zxx/README.md)
  includes 81 complex samples, saved mesh and replay inputs with a declared
  ideal reference plane.

On a disposable Marble copy, the grouped 3D case converged with 160 mA and
40 mA loads and a modeled copper loss of 0.10646 mW. The 3D electrical solution
uses tetrahedral copper with board-layer thermal feedback. The test applied
prescribed currents and illustrative cooling settings.
[Setup and limits](../quick_pi_plugin/ELECTROTHERMAL.md#marble-grouped-current-check)
