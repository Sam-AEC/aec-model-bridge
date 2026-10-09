; AEC Model Bridge - Inno Setup installer script.
;
; Built by scripts/build-installer.ps1 from the package that scripts/package.ps1 writes to
; dist\AECModelBridge (all four Revit years). Output: AECModelBridge-Setup-<AppVersion>.exe.
;
; What it installs (mirrors scripts/install.ps1):
;   C:\ProgramData\AECModelBridge\bin\<year>   add-in binaries, one folder per Revit year
;   C:\ProgramData\AECModelBridge\python       bundled Python with the MCP server
;   C:\ProgramData\AECModelBridge\config       default.json
;   %APPDATA%\Autodesk\Revit\Addins\<year>\AECModelBridge.addin   per-user manifest
;
; The installer never ships Autodesk assemblies (the Excludes below are a second line of
; defence behind the check in scripts/assert-no-autodesk-assemblies.ps1).
;
; Silent install: AECModelBridge-Setup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;   optional: /COMPONENTS="y2025,y2026"  /TASKS="mcpclients"  /SKIPWEBVIEW2=1  /LOG="setup.log"

#define Dist "..\..\dist\AECModelBridge"

[Setup]
AppId={{D41A24F3-87B1-4A51-9F31-30919E371C25}
AppName=AEC Model Bridge
AppVersion=1.3.3
AppPublisher=Sam-AEC
AppPublisherURL=https://github.com/Sam-AEC/aec-model-bridge
AppSupportURL=https://github.com/Sam-AEC/aec-model-bridge/issues
AppUpdatesURL=https://github.com/Sam-AEC/aec-model-bridge/releases
; The add-in and the bundled-Python lookup hard-code C:\ProgramData\AECModelBridge, so the
; install folder is fixed. Per-user install: no admin rights needed, and the manifest lands
; in the profile of the person who is actually running Setup (not an elevating admin).
DefaultDirName=C:\ProgramData\AECModelBridge
DisableDirPage=yes
DefaultGroupName=AEC Model Bridge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
MinVersion=10.0
OutputBaseFilename=AECModelBridge-Setup-{#SetupSetting("AppVersion")}
OutputDir=..\..\dist
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
UninstallDisplayName=AEC Model Bridge
WizardImageFile=..\..\assets\installer\wizard-large.bmp
WizardSmallImageFile=..\..\assets\installer\wizard-small.bmp
WizardStyle=modern
SetupLogging=yes
; Revit is checked explicitly in PrepareToInstall; never let Restart Manager close it.
CloseApplications=yes
RestartApplications=no

[Messages]
WelcomeLabel2=This installs [name/ver] for Autodesk Revit on your computer.%n%nClose Revit before you continue.
WizardSelectComponents=Revit versions
SelectComponentsDesc=Which Revit versions should AEC Model Bridge be installed for?
SelectComponentsLabel2=Versions of Revit found on this computer are already ticked. Change the selection if needed, then click Next.
FinishedLabelNoIcons=Setup has finished installing [name] on your computer.%n%nStart Revit and look for the AEC Bridge tab.
FinishedLabel=Setup has finished installing [name] on your computer.%n%nStart Revit and look for the AEC Bridge tab.

[Types]
Name: "full"; Description: "All supported Revit versions (2024 to 2027)"
Name: "custom"; Description: "Choose Revit versions"; Flags: iscustom

[Components]
Name: "y2024"; Description: "Revit 2024"; Types: full
Name: "y2025"; Description: "Revit 2025"; Types: full
Name: "y2026"; Description: "Revit 2026"; Types: full
Name: "y2027"; Description: "Revit 2027"; Types: full

[Tasks]
Name: "mcpclients"; Description: "Set up Claude Desktop and VS Code to use AEC Model Bridge (your current settings are backed up first)"; GroupDescription: "AI clients:"; Flags: unchecked

[InstallDelete]
; Start each Revit year from a clean folder so old and new DLLs are never mixed.
Type: filesandordirs; Name: "{app}\bin\2024"; Components: y2024
Type: filesandordirs; Name: "{app}\bin\2025"; Components: y2025
Type: filesandordirs; Name: "{app}\bin\2026"; Components: y2026
Type: filesandordirs; Name: "{app}\bin\2027"; Components: y2027
; Drop the previous server package before the new one is copied. Copying over the top leaves
; old aec_model_bridge-<version>.dist-info folders behind, and Python then reports the
; oldest one as the installed version (same fix as scripts/install.ps1).
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\aec_model_bridge-*.dist-info"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\revit_mcp_server-*.dist-info"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\revit_mcp_server"

[Files]
Source: "..\..\assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion

; Add-in binaries, one folder per Revit year.
Source: "{#Dist}\bin\2024\*"; DestDir: "{app}\bin\2024"; Components: y2024; Excludes: "RevitAPI.dll,RevitAPIUI.dll,AdWindows.dll,AdskLicensingSDK_*.dll"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Dist}\bin\2025\*"; DestDir: "{app}\bin\2025"; Components: y2025; Excludes: "RevitAPI.dll,RevitAPIUI.dll,AdWindows.dll,AdskLicensingSDK_*.dll"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Dist}\bin\2026\*"; DestDir: "{app}\bin\2026"; Components: y2026; Excludes: "RevitAPI.dll,RevitAPIUI.dll,AdWindows.dll,AdskLicensingSDK_*.dll"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Dist}\bin\2027\*"; DestDir: "{app}\bin\2027"; Components: y2027; Excludes: "RevitAPI.dll,RevitAPIUI.dll,AdWindows.dll,AdskLicensingSDK_*.dll"; Flags: ignoreversion recursesubdirs createallsubdirs

; Manifest template. The per-user manifests are written from it in [Code] (InstallManifests).
Source: "{#Dist}\addin\AECModelBridge.addin"; DestDir: "{app}\addin"; Flags: ignoreversion
Source: "{#Dist}\config\default.json"; DestDir: "{app}\config"; Flags: ignoreversion

; Bundled Python runtime with the MCP server already installed in Lib\site-packages.
Source: "{#Dist}\python\*"; DestDir: "{app}\python"; Excludes: "__pycache__"; Flags: ignoreversion recursesubdirs createallsubdirs

; Helper scripts used by [Run].
Source: "..\..\scripts\ensure-webview2.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\..\scripts\configure-mcp-clients.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

; Licence texts.
Source: "{#Dist}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Dist}\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Dist}\LICENSING.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Dist}\LICENSES\*"; DestDir: "{app}\LICENSES"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\ensure-webview2.ps1"""; StatusMsg: "Checking the WebView2 runtime..."; Flags: runhidden waituntilterminated; Check: WantWebView2
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\configure-mcp-clients.ps1"" -PythonPath ""{app}\python\python.exe"""; StatusMsg: "Setting up Claude Desktop and VS Code..."; Flags: runhidden waituntilterminated; Tasks: mcpclients

[UninstallDelete]
; The manifests are written by [Code], so Setup does not track them. The trailing * also
; removes any leftover .new or .bak file from an interrupted install.
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2024\AECModelBridge.addin*"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2025\AECModelBridge.addin*"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2026\AECModelBridge.addin*"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\2027\AECModelBridge.addin*"
; Remove everything else under the install folder (runtime caches, pyc files, logs).
Type: filesandordirs; Name: "{app}"

[Code]
const
  YearCount = 4;
  FirstYear = 2024;
  MOVEFILE_REPLACE_EXISTING = 1;

function MoveFileExW(lpExistingFileName, lpNewFileName: String; dwFlags: Cardinal): Integer;
  external 'MoveFileExW@kernel32.dll stdcall';

function YearAt(Index: Integer): String;
begin
  Result := IntToStr(FirstYear + Index);
end;

function UserAddinDir(const Year: String): String;
begin
  Result := ExpandConstant('{userappdata}') + '\Autodesk\Revit\Addins\' + Year;
end;

function CommonAddinDir(const Year: String): String;
begin
  Result := ExpandConstant('{commonappdata}') + '\Autodesk\Revit\Addins\' + Year;
end;

// A Revit year counts as installed when its program folder or one of its Addins folders exists.
function RevitDetected(const Year: String): Boolean;
begin
  Result :=
    DirExists(ExpandConstant('{commonpf64}') + '\Autodesk\Revit ' + Year) or
    DirExists(UserAddinDir(Year)) or
    DirExists(CommonAddinDir(Year));
end;

function IsRevitRunning: Boolean;
var
  Tmp: String;
  Output: AnsiString;
  ResultCode: Integer;
begin
  Result := False;
  Tmp := ExpandConstant('{tmp}') + '\aecmb-revit-check.txt';
  DeleteFile(Tmp);
  if Exec(ExpandConstant('{cmd}'),
      '/C tasklist /FI "IMAGENAME eq Revit.exe" /NH /FO CSV > "' + Tmp + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringFromFile(Tmp, Output) then
      Result := Pos('revit.exe', Lowercase(Output)) > 0;
  end;
  DeleteFile(Tmp);
end;

function WantWebView2: Boolean;
begin
  Result := ExpandConstant('{param:SKIPWEBVIEW2|0}') <> '1';
end;

// Preselect the Revit years found on this computer. An explicit /COMPONENTS= always wins,
// and when no Revit is found every year stays selected.
procedure InitializeWizard;
var
  I: Integer;
  Found: Boolean;
  Selection: String;
begin
  if ExpandConstant('{param:COMPONENTS|}') <> '' then
    Exit;

  Found := False;
  Selection := '';
  for I := 0 to YearCount - 1 do
  begin
    if RevitDetected(YearAt(I)) then
    begin
      Found := True;
      Selection := Selection + ',y' + YearAt(I);
    end
    else
      Selection := Selection + ',!y' + YearAt(I);
  end;

  if Found then
  begin
    Delete(Selection, 1, 1);
    WizardSelectComponents(Selection);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I: Integer;
  Any: Boolean;
begin
  Result := True;
  if CurPageID = wpSelectComponents then
  begin
    Any := False;
    for I := 0 to YearCount - 1 do
      if WizardIsComponentSelected('y' + YearAt(I)) then
        Any := True;
    if not Any then
    begin
      MsgBox('Select at least one Revit version.', mbInformation, MB_OK);
      Result := False;
    end;
  end;
end;

// Runs for silent installs too. A non-empty result aborts Setup before any file is written.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
  Any: Boolean;
begin
  Result := '';
  Any := False;
  for I := 0 to YearCount - 1 do
    if IsComponentSelected('y' + YearAt(I)) then
      Any := True;
  if not Any then
    Result := 'No Revit version is selected. Select at least one Revit version.'
  else if IsRevitRunning then
    Result := 'Revit is running. Close Revit, then run Setup again.';
end;

// Replace the text between <Assembly> and </Assembly> in the manifest template.
function RewriteAssembly(const Xml, AssemblyPath: String; var NewXml: String): Boolean;
var
  OpenPos, ClosePos: Integer;
begin
  OpenPos := Pos('<Assembly>', Xml);
  ClosePos := Pos('</Assembly>', Xml);
  Result := (OpenPos > 0) and (ClosePos > OpenPos);
  if Result then
    NewXml := Copy(Xml, 1, OpenPos + Length('<Assembly>') - 1) + AssemblyPath +
      Copy(Xml, ClosePos, Length(Xml));
end;

// Writes the per-user manifest for every selected year. Each manifest is written to
// <name>.new first and then moved over the real file in one step, so Revit only ever sees
// the old complete file or the new complete file. If any step fails, manifests already
// switched are put back and the function reports the error; the caller then fails the
// install and Setup rolls the copied files back.
function InstallManifests(var ErrorMsg: String): Boolean;
var
  I, J, Done: Integer;
  Year, Dir, Final, Xml, NewXml: String;
  Raw: AnsiString;
  Temps, Finals, Backups: TStringList;
begin
  Result := False;
  ErrorMsg := '';
  Done := 0;

  if not LoadStringFromFile(ExpandConstant('{app}') + '\addin\AECModelBridge.addin', Raw) then
  begin
    ErrorMsg := 'The add-in manifest template is missing from the installed files.';
    Exit;
  end;
  Xml := Raw;

  Temps := TStringList.Create;
  Finals := TStringList.Create;
  Backups := TStringList.Create;
  try
    // 1. Stage a complete new manifest for every selected year.
    for I := 0 to YearCount - 1 do
    begin
      Year := YearAt(I);
      if (ErrorMsg = '') and IsComponentSelected('y' + Year) then
      begin
        Dir := UserAddinDir(Year);
        Final := Dir + '\AECModelBridge.addin';
        if not ForceDirectories(Dir) then
          ErrorMsg := 'Could not create ' + Dir
        else if not RewriteAssembly(Xml,
            ExpandConstant('{app}') + '\bin\' + Year + '\AECModelBridge.dll', NewXml) then
          ErrorMsg := 'The add-in manifest template has no Assembly element.'
        else if not SaveStringToFile(Final + '.new', NewXml, False) then
          ErrorMsg := 'Could not write ' + Final + '.new'
        else
        begin
          Temps.Add(Final + '.new');
          Finals.Add(Final);
        end;
      end;
    end;

    // 2. Keep a copy of every manifest that is about to be replaced.
    if ErrorMsg = '' then
    begin
      for I := 0 to Finals.Count - 1 do
      begin
        if FileExists(Finals[I]) then
        begin
          if FileCopy(Finals[I], Finals[I] + '.bak', False) then
            Backups.Add(Finals[I] + '.bak')
          else
          begin
            Backups.Add('');
            ErrorMsg := 'Could not back up ' + Finals[I];
          end;
        end
        else
          Backups.Add('');
      end;
    end;

    // 3. Switch the new manifests in.
    if ErrorMsg = '' then
    begin
      for I := 0 to Finals.Count - 1 do
      begin
        if ErrorMsg = '' then
        begin
          if MoveFileExW(Temps[I], Finals[I], MOVEFILE_REPLACE_EXISTING) = 0 then
            ErrorMsg := 'Could not replace ' + Finals[I]
          else
            Done := Done + 1;
        end;
      end;
    end;

    // 4. On failure put the previous state back for everything already switched.
    if ErrorMsg <> '' then
    begin
      for J := 0 to Done - 1 do
      begin
        if (J < Backups.Count) and (Backups[J] <> '') then
          MoveFileExW(Backups[J], Finals[J], MOVEFILE_REPLACE_EXISTING)
        else
          DeleteFile(Finals[J]);
      end;
    end;

    // 5. Remove leftovers (staged files that were never switched in, and backups).
    for I := 0 to Temps.Count - 1 do
      DeleteFile(Temps[I]);
    for I := 0 to Backups.Count - 1 do
      if Backups[I] <> '' then
        DeleteFile(Backups[I]);

    Result := (ErrorMsg = '');

    // 6. Old layouts: remove the legacy manifest name and duplicates in the all-users folder
    //    (same clean-up as scripts/install.ps1). Failures here are not fatal.
    if Result then
    begin
      for I := 0 to Finals.Count - 1 do
      begin
        Year := ExtractFileName(ExtractFileDir(Finals[I]));
        DeleteFile(UserAddinDir(Year) + '\RevitBridge.addin');
        DeleteFile(CommonAddinDir(Year) + '\AECModelBridge.addin');
        DeleteFile(CommonAddinDir(Year) + '\RevitBridge.addin');
      end;
    end;
  finally
    Temps.Free;
    Finals.Free;
    Backups.Free;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Msg: String;
begin
  if CurStep = ssPostInstall then
  begin
    if not InstallManifests(Msg) then
      RaiseException('AEC Model Bridge could not write the Revit add-in manifest. ' + Msg +
        ' Nothing was changed in your Revit Addins folder.');
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  if IsRevitRunning then
  begin
    MsgBox('Revit is running. Close Revit, then run the uninstaller again.', mbInformation, MB_OK);
    Result := False;
  end;
end;
