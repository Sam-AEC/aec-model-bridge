param(
    [string]$Version = (Get-Content (Join-Path $PSScriptRoot '..\VERSION') -Raw).Trim(),
    # Use the dist\AECModelBridge folder as it is (CI builds it with build-release.ps1 first).
    [switch]$SkipPackage,
    # Where AECModelBridge-Setup-<version>.exe is written. Default: dist\
    [string]$OutputDir,
    # Add the installer to SHA256SUMS.txt in OutputDir (rewrites the whole file).
    [switch]$UpdateChecksums
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$distDir = Join-Path $repoRoot "dist\AECModelBridge"
$issPath = Join-Path $PSScriptRoot "installer\AECModelBridge.iss"
if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot "dist" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
$years = @("2024", "2025", "2026", "2027")

Write-Host "Building AEC Model Bridge installer $Version..." -ForegroundColor Cyan

# 0. The script is the single place the installer version lives next to VERSION.
$issVersion = [regex]::Match((Get-Content -LiteralPath $issPath -Raw), '(?m)^AppVersion=(.+?)\s*$').Groups[1].Value
if ($issVersion -ne $Version) {
    throw "AECModelBridge.iss has AppVersion=$issVersion but the version is $Version. Run: python scripts/version.py set $Version"
}

# 1. Make sure the package exists. The installer always carries every supported Revit year.
if (-not $SkipPackage) {
    Write-Host "`nRunning package script for all Revit years..." -ForegroundColor Yellow
    & "$PSScriptRoot\package.ps1" -Version $Version -RevitVersion All
    if ($LASTEXITCODE -ne 0) { throw "package.ps1 failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path -LiteralPath $distDir)) {
    throw "Package folder not found: $distDir. Run scripts\package.ps1 or omit -SkipPackage."
}
$required = @("python\python.exe", "addin\AECModelBridge.addin", "config\default.json", "LICENSE", "NOTICE", "LICENSING.md") +
    ($years | ForEach-Object { "bin\$_\AECModelBridge.dll" })
foreach ($rel in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $distDir $rel))) {
        throw "Installer payload is incomplete, missing dist\AECModelBridge\$rel (the installer needs the full package for 2024-2027, built with -RevitVersion All)."
    }
}
$sitePackages = Join-Path $distDir "python\Lib\site-packages"
if (-not (Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "revit_mcp_server" -ErrorAction SilentlyContinue)) {
    throw "The bundled Python has no revit_mcp_server package: $sitePackages"
}

# 2. Never ship Autodesk assemblies.
& "$PSScriptRoot\assert-no-autodesk-assemblies.ps1" -Path $distDir

# 3. Locate Inno Setup (ISCC.exe).
function Get-ISCCCompiler {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidatePaths = @()
    foreach ($major in @("6", "7")) {
        $candidatePaths += "${env:LOCALAPPDATA}\Programs\Inno Setup $major\ISCC.exe"
        $candidatePaths += "${env:ProgramFiles(x86)}\Inno Setup $major\ISCC.exe"
        $candidatePaths += "${env:ProgramFiles}\Inno Setup $major\ISCC.exe"
    }
    foreach ($path in $candidatePaths) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

$isccPath = Get-ISCCCompiler
if (-not $isccPath -and -not $env:CI) {
    Write-Host "`nInno Setup (ISCC.exe) not found. Attempting installation via winget..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements --silent
        $isccPath = Get-ISCCCompiler
    }
}
if (-not $isccPath) {
    throw "Inno Setup compiler (ISCC.exe) not found. Install Inno Setup 6 (choco install innosetup, or winget install JRSoftware.InnoSetup)."
}

# 4. Compile.
Write-Host "`nCompiling $issPath..." -ForegroundColor Yellow
Write-Host "  Using ISCC compiler: $isccPath" -ForegroundColor Gray
& $isccPath "/O$OutputDir" $issPath
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed with exit code $LASTEXITCODE" }

$installer = Join-Path $OutputDir "AECModelBridge-Setup-$Version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Installer build finished, but $installer was not found."
}

# 5. Optionally add it to SHA256SUMS.txt.
if ($UpdateChecksums) {
    $checksums = Get-ChildItem -Path $OutputDir -File |
        Where-Object Name -ne "SHA256SUMS.txt" |
        Sort-Object Name |
        ForEach-Object {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $($_.Name)"
        }
    $checksums | Set-Content -LiteralPath (Join-Path $OutputDir "SHA256SUMS.txt") -Encoding ascii
    Write-Host "  Updated SHA256SUMS.txt" -ForegroundColor Gray
}

Write-Host "`nInstaller built: $installer" -ForegroundColor Green
Write-Host "Size: $([math]::Round((Get-Item $installer).Length / 1MB, 2)) MB" -ForegroundColor Gray
Write-Host "SHA256: $((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant())" -ForegroundColor Gray
