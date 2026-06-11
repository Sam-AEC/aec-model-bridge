param(
    [string]$RevitVersion = "2024",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$supportedVersions = @("2024", "2025", "2026", "2027")

if ($supportedVersions -notcontains $RevitVersion) {
    Write-Error "Unsupported Revit version: $RevitVersion. Supported: $($supportedVersions -join ', ')"
    exit 1
}

# Path Guard: Prevent Execution in System32 or Windows
if ($PSScriptRoot -like "*C:\Windows*") {
    Write-Error "Dangerous path detected: $PSScriptRoot"
    Write-Error "Please clone the repo to a safe location (e.g., $env:USERPROFILE\src) and run from there."
    exit 1
}

$projectPath = "$PSScriptRoot\..\packages\revit-bridge-addin\RevitBridge.csproj"

if (-not (Test-Path $projectPath)) {
    Write-Error "Project not found: $projectPath"
    exit 1
}

$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnet) {
    Write-Error "dotnet not found. Install the .NET SDK versions documented for the selected Revit release."
    exit 1
}

Write-Host "Building AEC Model Bridge for Revit $RevitVersion ($Configuration)..." -ForegroundColor Cyan

& $dotnet.Source build $projectPath `
    -c $Configuration `
    -p:RevitVersion=$RevitVersion `
    -v:minimal

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$targetFramework = switch ($RevitVersion) {
    "2024" { "net48" }
    { $_ -in @("2025", "2026") } { "net8.0-windows" }
    "2027" { "net10.0-windows" }
}
$outputPath = Join-Path $PSScriptRoot "..\packages\revit-bridge-addin\bin\$Configuration\$RevitVersion\$targetFramework\AECModelBridge.dll"
Write-Host "Revit Build succeeded: $([System.IO.Path]::GetFullPath($outputPath))" -ForegroundColor Green

# Build Navisworks Add-in
$navisworksPath = "$PSScriptRoot\..\packages\navisworks-bridge-addin\NavisworksBridge.csproj"
if (Test-Path $navisworksPath) {
    Write-Host "Building AEC Model Bridge for Navisworks $RevitVersion ($Configuration)..." -ForegroundColor Cyan
    
    # Install to Navisworks 2026
    $navisTargetDir = "$env:APPDATA\Autodesk\Navisworks Manage 2026\Plugins\NavisworksBridge"
    if (-not (Test-Path $navisTargetDir)) {
        New-Item -ItemType Directory -Force -Path $navisTargetDir | Out-Null
    }
    
    & $dotnet.Source build $navisworksPath -c $Configuration -p:NavisworksVersion=$RevitVersion -v:minimal
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Navisworks build failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    
    # Navisworks Manage is still on .NET Framework 4.8 for 2024-2026
    $nwOutDir = Join-Path $PSScriptRoot "..\packages\navisworks-bridge-addin\bin\$Configuration\$RevitVersion\net48"
    $nwOutputPath = Join-Path $nwOutDir "NavisworksBridge.dll"
    
    if (Test-Path $nwOutDir) {
        Copy-Item "$nwOutDir\*" -Destination $navisTargetDir -Recurse -Force
        Write-Host "Navisworks Build succeeded and deployed: $([System.IO.Path]::GetFullPath($nwOutputPath))" -ForegroundColor Green
    } else {
        Write-Error "Could not find Navisworks output directory: $nwOutDir"
    }
}
