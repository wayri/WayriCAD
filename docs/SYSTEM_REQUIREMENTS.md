# System requirements


These are workload-based planning recommendations, rather than benchmarked minimums. Hardware needs grow with board complexity, mesh density, STEP model detail and transient duration; a cross-hardware performance benchmark suite is not yet available.

| Hardware | Everyday tools and smaller boards | Heavier PI, thermal and exact 3D mechanical studies |
|---|---|---|
| CPU | Modern 64-bit CPU with 4 or more physical cores and good single-core performance | 6–8 or more physical cores with strong sustained CPU performance; extra cores do not make every operation parallel |
| RAM | **16 GB recommended** | **32 GB recommended**; consider **64 GB** for larger meshes, detailed assemblies or concurrent studies |
| Storage | **SSD**, with roughly **20 GB free** for KiCad, libraries, plugin environments and working files | **SSD**, preferably NVMe, with **40 GB or more free** for additional models, caches, saved copies and reports |
| Graphics | Integrated or dedicated graphics with a working hardware-accelerated OpenGL driver | Dedicated graphics can improve large interactive 3D scenes; the current PI/thermal solvers use CPU calculations and do not require CUDA |
| Display | **1920 × 1080** or higher | **1920 × 1080** or higher; a larger display makes side panels and 3D inspection easier |

The storage figures are suggested free-space budgets, not fixed installation sizes. Graphics should meet [KiCad's official system requirements](https://www.kicad.org/help/system-requirements/), including OpenGL 2.1 or greater with hardware shaders. WayriCAD's native GUI checks currently cover Windows with KiCad 10; see [compatibility](COMPATIBILITY.md) for platform validation and each plugin's runtime dependencies. Exact mechanical checks also need FreeCAD; its setup is described in the [Mechanical Check guide](../mechanical_check_plugin/README.md#runtime).

**On an older laptop:** run one heavy analysis at a time, close unused applications and keep projects and dependency caches on an SSD. For initial PI/thermal previews, use a coarser mesh and a shorter transient study; refine the mesh and time settings and check convergence before relying on local peaks or heating times. Use [Mechanical Check's Quick 2D screen](../mechanical_check_plugin/README.md#quick-in-editor-screening) for an initial envelope review, then run exact 3D checks for solid clearances and collisions. A coarse preview or Quick 2D screen does not replace the detailed analysis.

