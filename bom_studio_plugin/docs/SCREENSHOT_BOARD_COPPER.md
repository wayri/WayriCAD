# Board and copper screenshot provenance

`../help-board-copper.png` shows the current Analytics Studio report panel on Windows, captured in headless Chrome through the application's local HTTP interface on 11 October 2026. The saved-board backend used Python 3.14 and Shapely 2.1.2. No report values were injected into the page. The server initializes its Shapely/GEOS geometry runtime on the host thread during startup. The first **Run analytics** request calculated the report through HTTP with no prior analytics call or cached report, returned 200, and passed the numerical assertions below. This check used a fresh application subprocess; the complete browser capture took about 1.9 seconds.

The source was a disposable, explicitly synthetic saved `.kicad_pcb` fixture, not a customer design or production validation board. It contains:

- A 20 × 15 mm rectangular outline and F.Cu/B.Cu copper layers.
- Two overlapping rectangular saved GND fills: 8 × 4 mm and 6 × 4 mm, overlapping by 2 × 4 mm. Their union is **48 mm²**, not the 56 mm² sum.
- U1: one 2 × 1 mm rectangular SMD pad on F.Cu.
- J1: one 2 mm round through-hole pad with a 1 mm drill.
- One 0.4 mm wide SIGNAL track from (12, 8) to (16, 10): length **√20 = 4.47213595 mm**.
- One through via, diameter 1 mm and drill diameter 0.5 mm, connecting F.Cu to B.Cu.

Assertions checked filled-area union **48 mm²**, **2 pads**, **1 via**, **known** geometry status, a saved-source SHA-256, and combined copper greater than fill-only area. The report shows **299.018647 mm²** laminate area after drill openings, **57.085251 mm²** copper summed across layer unions, and per-layer/net/component values computed by the backend's 128-segment circle approximation. These are geometric estimates, not electrical, manufacturing or thermal qualification.

Saved fixture SHA-256: `08cb285efdf204c2789a6aa0d5186d67f741ab3fe5052b48493330199ab88944`.

Privacy treatment: only the displayed project-path text and tooltip were replaced with `C:/Projects/AnalyticsDemo/AnalyticsDemo.kicad_pro` before capture. The screenshot was cropped to the report panel, so the header path is outside the image. No numerical values, component labels, geometry coverage or timestamps were redacted or altered. The image was visually inspected for private paths and identifiers.

The final capture includes the **Individual zones** table: the two saved fills have 32 mm² and 24 mm² separately, while the layer/net union remains 48 mm². Board report export keys are `board`, `copper_layers`, `copper_nets`, `copper_net_layers`, `copper_zones` and `pad_contacts`.
