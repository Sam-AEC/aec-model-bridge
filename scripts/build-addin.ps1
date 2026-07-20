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
# Unlike Revit (Nice3point NuGet fallback) and Rhino (RhinoCommon is a plain
# NuGet package), the Navisworks API has no public NuGet distribution at all -
# NavisworksBridge.csproj can only compile against a locally licensed
# Navisworks install (UseLocalNavisworks). CI runners never have one, so this
# step is best-effort like Rhino/Power BI below: warn and continue rather than
# fail the whole job over a build that is structurally impossible in CI.
$navisworksPath = "$PSScriptRoot\..\packages\navisworks-bridge-addin\NavisworksBridge.csproj"
if (Test-Path $navisworksPath) {
    Write-Host "Building AEC Model Bridge for Navisworks $RevitVersion ($Configuration)..." -ForegroundColor Cyan

    & $dotnet.Source build $navisworksPath -c $Configuration -p:NavisworksVersion=$RevitVersion -v:minimal
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Navisworks build skipped/failed (expected without a local licensed Navisworks install) - continuing." -ForegroundColor Yellow
    } else {
        # Navisworks Manage is still on .NET Framework 4.8 for 2024-2026
        $nwOutDir = Join-Path $PSScriptRoot "..\packages\navisworks-bridge-addin\bin\$Configuration\$RevitVersion\net48"
        $nwOutputPath = Join-Path $nwOutDir "NavisworksBridge.dll"
        Write-Host "Navisworks Build succeeded: $([System.IO.Path]::GetFullPath($nwOutputPath))" -ForegroundColor Green

        # Local dev convenience only: deploy straight into a running Navisworks 2026
        # install's plugin folder. Never attempted in CI (no such folder exists there).
        $navisTargetDir = "$env:APPDATA\Autodesk\Navisworks Manage 2026\Plugins\NavisworksBridge"
        if ((Test-Path "$env:APPDATA\Autodesk\Navisworks Manage 2026") -and (Test-Path $nwOutDir)) {
            New-Item -ItemType Directory -Force -Path $navisTargetDir | Out-Null
            Copy-Item "$nwOutDir\*" -Destination $navisTargetDir -Recurse -Force
            Write-Host "Deployed to $navisTargetDir" -ForegroundColor Green
        }
    }
}

# Build Rhino Add-in
$rhinoPath = "$PSScriptRoot\..\packages\rhino-bridge-addin\RhinoBridge.csproj"
if (Test-Path $rhinoPath) {
    Write-Host "Building AEC Model Bridge for Rhino ($Configuration)..." -ForegroundColor Cyan
    
    & $dotnet.Source build $rhinoPath -c $Configuration -v:minimal
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Rhino build failed with exit code $LASTEXITCODE"
        # Don't exit here so we don't fail the whole build if just Rhino fails
    } else {
        Write-Host "Rhino Build succeeded" -ForegroundColor Green
    }
}

# Build Power BI Tool
$pbiPath = "$PSScriptRoot\..\packages\powerbi-bridge-tool\PowerBIBridge.csproj"
if (Test-Path $pbiPath) {
    Write-Host "Building AEC Model Bridge for Power BI ($Configuration)..." -ForegroundColor Cyan
    
    & $dotnet.Source build $pbiPath -c $Configuration -v:minimal
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Power BI build failed with exit code $LASTEXITCODE"
    } else {
        Write-Host "Power BI Build succeeded" -ForegroundColor Green
        
        # Setup pbitool.json
        $pbiOutputDir = Join-Path $PSScriptRoot "..\packages\powerbi-bridge-tool\bin\$Configuration\net8.0-windows"
        $pbiJsonTemplate = Join-Path $PSScriptRoot "..\packages\powerbi-bridge-tool\AECModelBridge.pbitool.json"
        if (Test-Path $pbiJsonTemplate) {
            $jsonContent = Get-Content $pbiJsonTemplate -Raw
            $jsonContent = $jsonContent -replace "%PBITOOL_PATH%", $pbiOutputDir.Replace("\", "\\")
            
            $pbiExternalToolsDir = "C:\Program Files (x86)\Common Files\Microsoft Shared\Power BI Desktop\External Tools"
            if (-not (Test-Path $pbiExternalToolsDir)) {
                New-Item -ItemType Directory -Force -Path $pbiExternalToolsDir | Out-Null
            }
            try {
                Set-Content -Path (Join-Path $pbiExternalToolsDir "AECModelBridge.pbitool.json") -Value $jsonContent
                Write-Host "Registered Power BI External Tool." -ForegroundColor Green
            } catch {
                Write-Host "Could not register Power BI tool (requires admin rights). The tool was built successfully though." -ForegroundColor Yellow
            }
        }
    }
}
