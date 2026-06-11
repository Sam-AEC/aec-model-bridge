param(
    [string]$RevitYear = "2027",
    [switch]$AllUsers,
    [string]$AddinDir,
    [string]$AssemblyPath
)

$supportedVersions = @("2024", "2025", "2026", "2027")
if ($supportedVersions -notcontains $RevitYear) {
    throw "Unsupported Revit version: $RevitYear. Supported: $($supportedVersions -join ', ')"
}

if (-not $AddinDir) {
    $AddinDir = if ($AllUsers) {
        "C:\ProgramData\Autodesk\Revit\Addins"
    }
    else {
        Join-Path $env:APPDATA "Autodesk\Revit\Addins"
    }
}

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $AssemblyPath) {
    $AssemblyPath = "C:\ProgramData\AECModelBridge\bin\$RevitYear\AECModelBridge.dll"
}

$target = Join-Path $AddinDir $RevitYear
if (-not (Test-Path $target)) {
    New-Item -ItemType Directory -Path $target | Out-Null
}
$sourceManifest = Join-Path $repoRoot "packages\revit-bridge-addin\AECModelBridge.addin"
$targetManifest = Join-Path $target "AECModelBridge.addin"
[xml]$manifest = Get-Content -LiteralPath $sourceManifest -Raw
$manifest.RevitAddIns.AddIn.Assembly = [string][System.IO.Path]::GetFullPath($AssemblyPath)
$manifest.Save($targetManifest)
$legacyManifest = Join-Path $target "RevitBridge.addin"
if (Test-Path $legacyManifest) {
    Remove-Item -LiteralPath $legacyManifest -Force
}
Write-Host "Installed add-in manifest to $targetManifest"
