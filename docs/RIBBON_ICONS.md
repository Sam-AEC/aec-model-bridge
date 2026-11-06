# Ribbon icons ("cut slate")

The AEC Bridge tab uses the same icon style as the Recipe Editor pyRevit tab: a solid silhouette with the detail cut out, slate on the light ribbon and near-white on the dark one, one Autodesk-blue (#0696D7) block for the subject, at most one small Dutch-orange (#FF6C00) piece for the action, 1 px gaps, and a light top-to-bottom gradient with a darker bottom edge.

**Regenerate.** `python scripts/make_ribbon_icons.py` (Pillow, offline, deterministic) writes `packages/revit-bridge-addin/Resources/RibbonIcons/<name>_<16|32>_<light|dark>.png`. Add `--preview artifacts/ribbon-preview.png --refs <folder with a ribbon screenshot 3.png>` for a contact sheet (mock ribbon, dark and light, 100 % and 200 %, 4x zoom).

**Wiring.** `RevitBridge.csproj` embeds the PNGs as `RevitBridge.RibbonIcons.<file>`. Each `IconGenerator.Create*Icon(size)` first calls `LoadEmbedded(name, size)`, which picks the `light` or `dark` file from `UIThemeManager.CurrentTheme`; the old vector drawing is the fallback when a resource is missing. `App.cs` still writes `Icons\*.png` next to the DLL at start-up, and `RefreshRibbonIcons` swaps every button when Revit's theme changes. The About button uses `about` (the cerberus mark); the brand tile stays the tooltip image. Names: connect, disconnect, status, panel, healthcheck, pending, reports, settings (Config), help, about.

**Deploy (owner, only after closing Revit).**

1. Close every Revit session. The add-in is the live MCP bridge, so tell anyone who uses it first.
2. `git switch ribbon-cut-slate`
3. `.\scripts\deploy-addin.ps1 -RevitYear 2024`. This builds Release, refuses to run while Revit.exe is running, backs up the current `C:\ProgramData\AECModelBridge\bin\2024` to `C:\ProgramData\AECModelBridge\backup\2024-<timestamp>`, copies the whole output folder, and checks the copy. You do not need to copy any files yourself.
4. Start Revit and open the AEC Bridge tab. Switch the theme (Options > User Interface) to check both variants.

**Roll back.** Close Revit. Run `git switch dev` (or `main`), then `.\scripts\deploy-addin.ps1 -RevitYear 2024`. Or copy the backup folder from step 3 back to `C:\ProgramData\AECModelBridge\bin\2024`.
