; AEC Model Bridge — Inno Setup Installer Script
; Compiles to AECModelBridgeSetup.exe

[Setup]
AppId={{D41A24F3-87B1-4A51-9F31-30919E371C25}
AppName=AEC Model Bridge
AppVersion=1.1.0
AppPublisher=Sam-AEC
AppPublisherURL=https://github.com/Sam-AEC/aec-model-bridge
DefaultDirName=C:\ProgramData\AECModelBridge
DefaultGroupName=AEC Model Bridge
DisableProgramGroupPage=yes
OutputBaseFilename=AECModelBridgeSetup
OutputDir=..\..\dist
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Files]
Source: "..\..\dist\AECModelBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\scripts\ensure-webview2.ps1"""; StatusMsg: "Checking WebView2 Runtime..."; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install.ps1"" -RevitVersion All -DistPath ""{app}"""; StatusMsg: "Installing AEC Model Bridge components..."; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\scripts\configure-mcp-clients.ps1"" -PythonPath ""{app}\python\python.exe"""; StatusMsg: "Configuring MCP clients (Claude Desktop / VS Code)..."; Flags: runhidden waituntilterminated
