# Smoke test for AECModelBridge-Setup-<version>.exe: silent install, upgrade, failure and uninstall.
#
# DESTRUCTIVE: it installs into C:\ProgramData\AECModelBridge and writes a Revit manifest in
# %APPDATA%, then uninstalls. It refuses to run when an install already exists unless
# -AllowOverwrite is given. Meant for CI runners and throw-away VMs, not a working machine.
param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [string]$Year = "2026",
    [switch]$AllowOverwrite
)

$ErrorActionPreference = "Stop"

$Installer = (Resolve-Path -LiteralPath $Installer).Path
$appDir = "C:\ProgramData\AECModelBridge"
$addinDir = Join-Path $env:APPDATA "Autodesk\Revit\Addins\$Year"
$manifest = Join-Path $addinDir "AECModelBridge.addin"
$logDir = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }

if (-not $AllowOverwrite -and ((Test-Path -LiteralPath $appDir) -or (Test-Path -LiteralPath $manifest))) {
    throw "An AEC Model Bridge install already exists on this machine. Re-run with -AllowOverwrite only on a throw-away machine."
}

function Assert-That {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "FAILED: $Message" }
    Write-Host "  ok: $Message" -ForegroundColor Green
}

function Invoke-Setup {
    param([string]$Name)
    $log = Join-Path $logDir "aecmb-setup-$Name.log"
    $setupArgs = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/COMPONENTS=y$Year", "/SKIPWEBVIEW2=1", "/LOG=`"$log`"")
    $p = Start-Process -FilePath $Installer -ArgumentList $setupArgs -Wait -PassThru
    Write-Host "  setup log: $log (exit code $($p.ExitCode))"
    return $p.ExitCode
}

# --- 1. A failure while writing the manifest must not leave a manifest behind. ---------------
Write-Host "`n[1] Failure injection" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $addinDir -Force | Out-Null
$blocker = "$manifest.new"
New-Item -ItemType Directory -Path $blocker -Force | Out-Null   # SaveStringToFile cannot write over a folder
$code = Invoke-Setup "failure"
Assert-That ($code -ne 0) "setup reports failure when the manifest cannot be written (exit code $code)"
Assert-That (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) "no manifest was left behind"
Remove-Item -LiteralPath $blocker -Recurse -Force
Write-Host "  leftover install folder after the failed run: $(Test-Path -LiteralPath $appDir)"

# --- 2. Clean install -------------------------------------------------------------------------
Write-Host "`n[2] Silent install for Revit $Year" -ForegroundColor Cyan
$code = Invoke-Setup "install"
Assert-That ($code -eq 0) "setup exits with 0 (got $code)"
$dll = Join-Path $appDir "bin\$Year\AECModelBridge.dll"
Assert-That (Test-Path -LiteralPath $dll) "bridge DLL installed: $dll"
foreach ($other in @("2024", "2025", "2026", "2027") | Where-Object { $_ -ne $Year }) {
    Assert-That (-not (Test-Path -LiteralPath (Join-Path $appDir "bin\$other"))) "year $other was not installed"
}
Assert-That (Test-Path -LiteralPath $manifest -PathType Leaf) "manifest written: $manifest"
[xml]$xml = Get-Content -LiteralPath $manifest -Raw
Assert-That ($xml.RevitAddIns.AddIn.Assembly -eq $dll) "manifest Assembly points to $dll"
Assert-That (-not (Test-Path -LiteralPath "$manifest.new")) "no temporary manifest left"
Assert-That (Test-Path -LiteralPath (Join-Path $appDir "config\default.json")) "default.json installed"
$python = Join-Path $appDir "python\python.exe"
Assert-That (Test-Path -LiteralPath $python) "bundled Python installed"
& $python -c "import revit_mcp_server"
Assert-That ($LASTEXITCODE -eq 0) "bundled Python imports revit_mcp_server"
$autodesk = Get-ChildItem -Path $appDir -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @("RevitAPI.dll", "RevitAPIUI.dll", "AdWindows.dll") -or $_.Name -like "AdskLicensingSDK_*.dll" }
Assert-That (-not $autodesk) "no Autodesk assemblies in the install folder"

# --- 3. Upgrade removes stale server metadata -------------------------------------------------
Write-Host "`n[3] Upgrade over the top" -ForegroundColor Cyan
$site = Join-Path $appDir "python\Lib\site-packages"
$stale = Join-Path $site "aec_model_bridge-0.0.1.dist-info"
New-Item -ItemType Directory -Path $stale -Force | Out-Null
$code = Invoke-Setup "upgrade"
Assert-That ($code -eq 0) "second setup exits with 0 (got $code)"
Assert-That (-not (Test-Path -LiteralPath $stale)) "stale aec_model_bridge dist-info was removed"
$distInfo = @(Get-ChildItem -LiteralPath $site -Directory -Filter "aec_model_bridge-*.dist-info")
Assert-That ($distInfo.Count -eq 1) "exactly one aec_model_bridge dist-info remains ($($distInfo.Name -join ', '))"

# --- 4. Uninstall -----------------------------------------------------------------------------
Write-Host "`n[4] Silent uninstall" -ForegroundColor Cyan
$uninstaller = Get-ChildItem -LiteralPath $appDir -Filter "unins*.exe" | Select-Object -First 1
Assert-That ($null -ne $uninstaller) "uninstaller exists"
Start-Process -FilePath $uninstaller.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait | Out-Null
for ($i = 0; $i -lt 60 -and (Test-Path -LiteralPath $appDir); $i++) { Start-Sleep -Seconds 1 }
Assert-That (-not (Test-Path -LiteralPath $manifest)) "manifest removed"
Assert-That (-not (Test-Path -LiteralPath $appDir)) "$appDir removed"

Write-Host "`nInstaller smoke test passed." -ForegroundColor Green
