# Fails when a folder contains Autodesk assemblies, which must never be redistributed.
# Used by build-release.ps1 (the packaged dist) and build-installer.ps1 (the installer payload).
param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

$prohibitedNames = @(
    "RevitAPI.dll",
    "RevitAPIUI.dll",
    "AdWindows.dll",
    "AdskLicensingSDK_*.dll"
)
$prohibitedFiles = foreach ($pattern in $prohibitedNames) {
    Get-ChildItem -Path $Path -Recurse -File -Filter $pattern -ErrorAction SilentlyContinue
}
if ($prohibitedFiles) {
    $paths = ($prohibitedFiles.FullName | Sort-Object -Unique) -join [Environment]::NewLine
    throw "Release contains Autodesk assemblies and cannot be published:$([Environment]::NewLine)$paths"
}
