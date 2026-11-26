# Ribbon layout and icons

**Layout.** The AEC Bridge tab has two panels.

- Model Bridge: Panel (open the dockable panel), Approve (the approval queue), Check model (health check).
- Connection: one large toggle that reads Connected or Disconnected and starts or stops the bridge server. Its slide-out holds Status, Config, Reports, Help and About.

There is no Dev panel. The hub signs `.dev-mode.json` and only the hub can verify it, so the add-in has no reliable Dev mode signal. Reports sits in the slide-out instead.

**Code.** `Bridge/App.cs` builds the ribbon. `CommandToggleConnection` (`Bridge/BridgeCommands.cs`) flips the server and calls `App.RefreshConnectionButton`, which updates the text, tooltip and icon. `CommandConnect` and `CommandDisconnect` stay available but are not on the ribbon.

**Regenerate icons.** `pip install resvg-py`, then `python scripts/make_ribbon_icons.py`. It reads the Fluent glyphs from the icon kit (`--fluent path/to/fluent_lib.json`), renders `assets/logo-mark.svg` for Panel, and writes `packages/revit-bridge-addin/Resources/RibbonIcons/<name>_<16|32>_<dark|light>.png`. Names: panel, approve, healthcheck, connected, disconnected, status, settings, reports, help, about. The glyphs are MIT licensed; the notice is in `NOTICE`.

**Wiring.** `RevitBridge.csproj` embeds the PNGs as `RevitBridge.RibbonIcons.<file>`. Each `IconGenerator.Create*Icon(size)` calls `LoadEmbedded(name, size)`, which picks the `dark` or `light` file from `UIThemeManager.CurrentTheme`; the old vector drawing is the fallback when a resource is missing. `App.cs` tracks every button, and `RefreshRibbonIcons` swaps the images when Revit's theme changes.

**Deploy (owner, only after closing Revit).**

1. Close every Revit session. The add-in is the live MCP bridge, so tell anyone who uses it first.
2. `.\scripts\deploy-addin.ps1 -RevitYear 2024`. This builds Release, refuses to run while Revit.exe is running, backs up the current `C:\ProgramData\AECModelBridge\bin\2024` to `C:\ProgramData\AECModelBridge\backup\2024-<timestamp>`, copies the whole output folder, and checks the copy.
3. Start Revit and open the AEC Bridge tab. Switch the theme (Options > User Interface) to check both variants.

**Roll back.** Close Revit. Check out the previous version and run `.\scripts\deploy-addin.ps1 -RevitYear 2024`. Or copy the backup folder from step 2 back to `C:\ProgramData\AECModelBridge\bin\2024`.
