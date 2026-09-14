# WayriCAD BOM Studio 0.8.3 — Full PCM installer

**Install `WayriCAD_BOM_Studio_0.8.3_PCM.zip` directly in KiCad Manager → Plugin and Content Manager → Install from File. Leave it compressed.**

This is the complete plugin, not a patch, profile-only pack or archive to merge manually. It retains the full 0.8.2 implementation and adds integrated per-board assembler exports. No profile JSON editing is needed for the built-in selections.

## Install / upgrade

1. Quit old WayriCAD sessions, close KiCad and back up the project/sidecar and the whole catalogue directory. Keep catalogues outside plugin installation folders.
2. In PCM select this ZIP with Install from File and apply the install/update. The package ID remains `org.wayricad.bomstudio`.
3. Let plugin environment setup finish, restart KiCad and launch the standard BOM-icon action from PCB Editor. The runtime badge should show **v0.8.3 · Desktop window**.

Do not run the old manual installer or import the standalone profile pack. A duplicate old manual plugin may shadow the PCM action; the runtime diagnostic reports the actual path/version and scans common locations. Move obsolete copies outside scanned plugin directories, not merely to a differently named subfolder. Do not move/delete your project or catalogue.

The default is a **separate modeless plugin-owned window with an embedded browser**, not a browser tab or a docked native KiCad panel. The desktop-only toolbar refuses browser-mode overrides and never silently falls back. The explicit troubleshooting CLI `gui PROJECT --ui browser` remains available.

Python 3.10+ is required. KiCad provisions `kicad-python==0.8.0` and platform-specific `pywebview==6.2.1` dependencies. Windows needs WebView2; macOS uses WebKit/Cocoa; Linux uses Qt/system dependencies. First-time setup may need internet/package access. Wheels, browser runtimes, KiCad and fonts are not bundled. Recreate the plugin environment where available if dependency provisioning failed. Optional STEP/IGES/BREP previews keep their separate requirements-preview.txt.

## New workflow

Open **OEM / assembly export**. Choose JLCPCB, PCBWay, HQPCB, NextPCB, Sierra Circuits, PCB Power, Seeed Fusion or Generic assembler. Preview the actual headings and component rows; review provider notes and acknowledge mappings where required. Export a single **CSV / Excel (.xlsx)** file or a **ZIP with all selected alternatives**. Optional TSV also needs recipient-support review.

Assembly quantities are **per board** and equal the explicit designator count. The program does not apply purchasing board quantities, attrition or MOQ/multiples. Enter the actual board count separately at the assembler. Selected providers are alternative quotations, not separate orders. Existing **Vendor split & upload** still handles DigiKey/Mouser and purchasing quantities independently.

JLCPCB defaults to four columns (Comment, Designator, Footprint, LCSC Part #). LCSC codes are not taken from DigiKey/Mouser SKUs. Other mappings can be adjusted in the built-in column editor. Full descriptions can come from your chosen Description property. Physical properties and native templates are never rewritten by assembler export.

JLCPCB, Sierra and PCB Power mappings are documentation-guided, not production-portal certified. PCBWay, HQPCB, NextPCB, Seeed and Generic layouts require explicit review against the recipient's current importer/template. **Actual authenticated portal imports have not been tested.** No CPL, Gerbers, automatic upload, live inventory or order is generated. Unresolved source/rule-area checks still block guessed assembly population.

## Retained capabilities

KiCad-first field-name templates, native BOM/presets, explicit customization and reviewed writeback; desktop-only launcher; cataloguing, library creation and captured symbol/footprint/3D preview; independent variants; direct/bulk editing and search; price/mass/power analytics; supplier evidence and vendor splitting; qualification/reviews; multi-build planning; full CLI and job-set pipelines are included.

## CLI

From the installed plugin directory (not required for normal GUI use):

```powershell
py -3 .\cli.py assemblers --list-profiles
py -3 .\cli.py assemblers "C:\Projects\Board\Board.kicad_pro" --profile jlcpcb --format xlsx --output ".\JLCPCB_BOM.xlsx"
py -3 .\cli.py assemblers "C:\Projects\Board\Board.kicad_pro" --all-profiles --acknowledge-profile-review --format zip --output ".\Assembler_BOMs.zip"
```

The last command explicitly acknowledges review-required mappings; inspect them first. Output paths must be new. A pipeline can include assembler_exports with the same settings. No hidden native writes occur.

## Acceptance boundary

Read the supplied TEST_REPORT for the actual results. PCM structure/schema checks and automated tests do not establish real KiCad-host installation, Windows/macOS embedded-window acceptance, live IPC selection/focus, native writeback/model loading, native job-set execution, future KiCad 11 compatibility or production provider uploads. Those remain target-system checks. This is a packaged developer preview, not manufacturing approval.

Start with TRY_ENGINEERING_SAMPLE_WINDOWS.bat or a disposable project copy. The examples contain fictional DEMO identities and are not ordering data. Current guides take precedence over older versioned/historical documentation.
