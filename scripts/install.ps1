param(
    [string]$RevitVersion = "2027",
    [string]$Version = "1.0.2",
    [switch]$AllUsers,
    [string]$DistPath
)

$ErrorActionPreference = "Stop"

if (-not $DistPath) {
    $packagedLayout = Test-Path -LiteralPath (Join-Path $PSScriptRoot "bin")
    $DistPath = if ($packagedLayout) {
        $PSScriptRoot
    }
    else {
        Join-Path $PSScriptRoot "..\dist\AECModelBridge"
    }
}
$DistPath = [System.IO.Path]::GetFullPath($DistPath)

Write-Host "AEC Model Bridge Installer" -ForegroundColor Cyan
Write-Host "==================`n" -ForegroundColor Cyan

# Path Guard: Prevent Execution in System32 or Windows
if ($PSScriptRoot -like "*C:\Windows*") {
    Write-Error "Dangerous path detected: $PSScriptRoot"
    Write-Error "Please clone the repo to a safe location (e.g., $env:USERPROFILE\src) and run from there."
    exit 1
}

# Verify dist package exists, or auto-build it
if (-not (Test-Path $DistPath)) {
    Write-Host "Distribution package not found at: $DistPath" -ForegroundColor Yellow
    Write-Host "Auto-triggering packaging for Revit $RevitVersion..." -ForegroundColor Cyan
    & "$PSScriptRoot\package.ps1" -RevitVersion $RevitVersion -Version $Version
    
    if (-not (Test-Path $DistPath)) {
        Write-Error "Packaging failed. Please run .\scripts\package.ps1 manually to diagnose."
        exit 1
    }
}

# Install binaries to a version-specific ProgramData directory so supported
# Revit releases can coexist without overwriting one another.
Write-Host "Installing binaries..." -ForegroundColor Yellow
$targetBin = "C:\ProgramData\AECModelBridge\bin\$RevitVersion"
New-Item -ItemType Directory -Path $targetBin -Force | Out-Null

$sourceBin = "$DistPath\bin\$RevitVersion"
if (-not (Test-Path $sourceBin)) {
    Write-Error "Binaries for Revit $RevitVersion not found in distribution package.`nAvailable versions: $((Get-ChildItem "$DistPath\bin" -Directory).Name -join ', ')"
    exit 1
}

Copy-Item "$sourceBin\*" $targetBin -Recurse -Force
Write-Host "  Installed to: $targetBin" -ForegroundColor Green

# Install add-in manifest
Write-Host "`nInstalling add-in manifest..." -ForegroundColor Yellow
$addinDir = if ($AllUsers) {
    "C:\ProgramData\Autodesk\Revit\Addins\$RevitVersion"
}
else {
    "$env:APPDATA\Autodesk\Revit\Addins\$RevitVersion"
}

New-Item -ItemType Directory -Path $addinDir -Force | Out-Null
$sourceManifest = Join-Path $DistPath "addin\AECModelBridge.addin"
$targetManifest = Join-Path $addinDir "AECModelBridge.addin"
[xml]$manifest = Get-Content -LiteralPath $sourceManifest -Raw
$manifest.RevitAddIns.AddIn.Assembly = [string](Join-Path $targetBin "AECModelBridge.dll")
$manifest.Save($targetManifest)
$legacyManifest = Join-Path $addinDir "RevitBridge.addin"
if (Test-Path $legacyManifest) {
    Remove-Item -LiteralPath $legacyManifest -Force
    Write-Host "  Removed legacy manifest: $legacyManifest" -ForegroundColor Gray
}

$otherAddinDir = if ($AllUsers) {
    "$env:APPDATA\Autodesk\Revit\Addins\$RevitVersion"
}
else {
    "C:\ProgramData\Autodesk\Revit\Addins\$RevitVersion"
}
foreach ($duplicateName in @("AECModelBridge.addin", "RevitBridge.addin")) {
    $duplicateManifest = Join-Path $otherAddinDir $duplicateName
    if (Test-Path -LiteralPath $duplicateManifest) {
        try {
            Remove-Item -LiteralPath $duplicateManifest -Force
            Write-Host "  Removed duplicate manifest: $duplicateManifest" -ForegroundColor Gray
        }
        catch {
            Write-Warning "Could not remove duplicate manifest: $duplicateManifest"
        }
    }
}
Write-Host "  Installed to: $addinDir" -ForegroundColor Green

$legacyBinRoot = "C:\ProgramData\AECModelBridge\bin"
$legacyAssembly = Join-Path $legacyBinRoot "AECModelBridge.dll"
if (Test-Path -LiteralPath $legacyAssembly) {
    $manifestRoots = @(
        "$env:APPDATA\Autodesk\Revit\Addins",
        "C:\ProgramData\Autodesk\Revit\Addins"
    )
    $legacyReferences = foreach ($manifestRoot in $manifestRoots) {
        if (Test-Path -LiteralPath $manifestRoot) {
            Get-ChildItem -LiteralPath $manifestRoot -Recurse -Filter "*.addin" -File -ErrorAction SilentlyContinue |
                Where-Object {
                    (Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue) -match
                        [regex]::Escape($legacyAssembly)
                }
        }
    }

    if (-not $legacyReferences) {
        Get-ChildItem -LiteralPath $legacyBinRoot -File -ErrorAction SilentlyContinue |
            Remove-Item -Force
        Write-Host "  Removed obsolete shared binary files from: $legacyBinRoot" -ForegroundColor Gray
    }
    else {
        Write-Warning "Legacy shared binaries remain because another add-in manifest still references them."
    }
}

# Copy config (optional)
Write-Host "`nCopying default configuration..." -ForegroundColor Yellow
$configTarget = "C:\ProgramData\AECModelBridge\config"
New-Item -ItemType Directory -Path $configTarget -Force | Out-Null
Copy-Item "$DistPath\config\default.json" $configTarget -Force
Write-Host "  Installed to: $configTarget\default.json" -ForegroundColor Green

# Installation summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`nInstalled components:" -ForegroundColor Yellow
Write-Host "  Bridge DLL:    $targetBin\AECModelBridge.dll"
Write-Host "  Add-in:        $targetManifest"
Write-Host "  Config:        $configTarget\default.json"

Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "  1. Restart Revit $RevitVersion" -ForegroundColor White
Write-Host "  2. Open a project in Revit" -ForegroundColor White
Write-Host "  3. Verify bridge: curl http://127.0.0.1:3000/health" -ForegroundColor White
Write-Host "  4. Expected response: {`"status`":`"healthy`",`"revit_version`":`"$RevitVersion`",...}" -ForegroundColor Gray

Write-Host "`nTo install MCP server:" -ForegroundColor Yellow
if (Test-Path "$DistPath\server\revit_mcp_server.exe") {
    Write-Host "  Run: $DistPath\server\revit_mcp_server.exe" -ForegroundColor White
}
else {
    $wheel = Get-ChildItem "$DistPath\server\*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($wheel) {
        Write-Host "  pip install $($wheel.FullName)" -ForegroundColor White
        Write-Host "  python -m revit_mcp_server" -ForegroundColor White
    }
}

Write-Host "`nTroubleshooting:" -ForegroundColor Yellow
Write-Host "  - Check Revit journal: %LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit $RevitVersion\Journals\" -ForegroundColor Gray
Write-Host "  - Check bridge logs: %APPDATA%\AECModelBridge\Logs\bridge.jsonl" -ForegroundColor Gray
Write-Host "  - Uninstall: Remove files from paths above" -ForegroundColor Gray
