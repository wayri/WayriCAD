# Readable windows, panels and tables

WayriCAD 3.6.20 makes settings, previews and results easier to resize. It does not shrink fonts to fit a crowded window.

## Make room for a panel

- Drag the divider between settings and the board preview. Analysis tools also have adjustable results or inspector areas.
- Open optional details only when needed. Expanded settings scroll inside their own area; the surrounding window no longer needs to grow with them.
- In Analytics Studio and Constraint Studio, scroll wide tables horizontally. Drag the bottom edge of supported tables, net lists and scope panels to make them taller. Narrow windows stack their sections.
- Maximize the window for large boards. Initial native windows are constrained to the current display work area where the shared layout helper is installed.

Fanout, Via Stitching, Heater Designer, Copper Balancer, Planar Magnetics, Quick PI, QuickTherm, Quick SI, Trace RLC, Fusion, Variant Manager, Component Arranger, Trace Refiner, Silkscreen Labels and Layer Counter have adjustable settings/preview layouts. Embed3D uses a scrolling main workspace. Settings dialogs retain their tool-specific workflow.

## Read complete table values

In supported native tables, focus the table and press **Ctrl+Shift+Enter**. A resizable reader shows complete row values with a search box. Drag its divider to give the value area more room. **Ctrl+C** copies selected rows, including headers. Existing table selection and double-click navigation remain available.

The reader supports report-style ListCtrl tables, grids and indexed data views. Hierarchical trees retain their own inspector. On Windows, long ListCtrl values are read without wxPython's 512-character retrieval limit; exceptionally large cells above 262,143 characters require the exported report. The reader takes a snapshot when opened, so reopen it after results change.

## Find help

Use the visible **Help** action or **F1** where supported. Every plugin ships an offline HTML guide with its workflow, input requirements, result interpretation, limitations and recovery steps. [Browse all 23 guides](HELP_INDEX.md).

Analytics Studio opens its bundled guide from the header or Compatibility & help. No external website is needed to read it. Internet access may still be required for dependency setup.

## Validation limits

Native window and splitter checks were run on Windows with KiCad 10.0.6 at 1024×720. Browser layout checks and portable CI are recorded in the [release audit](audits/RELEASE_3.6.20.md). Native Linux/macOS interfaces and every display scaling factor have not been verified. If a specific window still clips, report the plugin, window size, display scale and panel involved.
