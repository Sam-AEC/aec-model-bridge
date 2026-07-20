param(
    [string]$RevitVersion = "All"
)

$ErrorActionPreference = "Stop"

Write-Host "Building AEC Model Bridge Double-Click Installer..." -ForegroundColor Cyan

# 1. Ensure package is built
$distDir = Join-Path $PSScriptRoot "..\dist\AECModelBridge"
Write-Host "`nRunning package script for Revit $RevitVersion..." -ForegroundColor Yellow
& "$PSScriptRoot\package.ps1" -RevitVersion $RevitVersion

if (-not (Test-Path $distDir)) {
    Write-Error "Packaging failed - dist folder $distDir does not exist."
    exit 1
}

# 2. Locate or install Inno Setup (ISCC.exe)
function Get-ISCCCompiler {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidatePaths = @(
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidatePaths) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            return $path
        }
    }
    return $null
}

$isccPath = Get-ISCCCompiler

if (-not $isccPath) {
    Write-Host "`nInno Setup (ISCC.exe) not found. Attempting auto-installation via winget..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements --silent
        $isccPath = Get-ISCCCompiler
    }
}

if (-not $isccPath) {
    Write-Error "Inno Setup compiler (ISCC.exe) could not be located or installed. Please install Inno Setup 6."
    exit 1
}

# 3. Compile Inno Setup Script
$issPath = Join-Path $PSScriptRoot "installer\AECModelBridge.iss"
Write-Host "`nCompiling Inno Setup script: $issPath..." -ForegroundColor Yellow
Write-Host "  Using ISCC compiler: $isccPath" -ForegroundColor Gray

& "$isccPath" "$issPath"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup compilation failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$outputInstaller = Join-Path $PSScriptRoot "..\dist\AECModelBridgeSetup.exe"
if (Test-Path $outputInstaller) {
    Write-Host "`nDouble-click installer successfully built!" -ForegroundColor Green
    Write-Host "Location: $outputInstaller" -ForegroundColor Cyan
    Write-Host "Size: $([math]::Round((Get-Item $outputInstaller).Length / 1MB, 2)) MB" -ForegroundColor Gray
} else {
    Write-Error "Installer build finished, but output installer was not found at $outputInstaller"
    exit 1
}
