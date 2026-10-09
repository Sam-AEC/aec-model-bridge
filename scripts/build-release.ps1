param(
    [string]$Version = (Get-Content (Join-Path $PSScriptRoot '..\VERSION') -Raw).Trim(),
    [string]$RevitVersion = "All",
    [string]$VSCodePackage,
    [switch]$UpdateServerMetadata
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$distRoot = Join-Path $repoRoot "dist"
$packageDir = Join-Path $distRoot "AECModelBridge"
$releaseDir = Join-Path $distRoot "release"
$mcpbStage = Join-Path $distRoot "mcpb-stage"
$zipStageRoot = Join-Path $distRoot "zip-stage"
$supportedYears = @("2024", "2025", "2026", "2027")
$years = if ($RevitVersion -eq "All") { $supportedYears } else { @($RevitVersion) }

if ($VSCodePackage) {
    $vsixPath = (Resolve-Path -LiteralPath $VSCodePackage -ErrorAction Stop).Path
    if ((Split-Path -Leaf $vsixPath) -ne "aec-model-bridge-$Version.vsix") {
        throw "VS Code package must match release version: aec-model-bridge-$Version.vsix"
    }
}

function Remove-WorkspaceDirectory {
    param([string]$Path)

    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repository: $resolved"
    }

    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

Remove-WorkspaceDirectory $packageDir
Remove-WorkspaceDirectory $releaseDir
Remove-WorkspaceDirectory $mcpbStage
Remove-WorkspaceDirectory $zipStageRoot
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

& (Join-Path $PSScriptRoot "package.ps1") -Version $Version -RevitVersion $RevitVersion
if ($LASTEXITCODE -ne 0) {
    throw "Distribution packaging failed with exit code $LASTEXITCODE"
}

foreach ($year in $years) {
    $bridgeDll = Join-Path $packageDir "bin\$year\AECModelBridge.dll"
    if (-not (Test-Path -LiteralPath $bridgeDll)) {
        throw "Expected bridge assembly was not produced: $bridgeDll"
    }
}

# Shared with build-installer.ps1 so the zips and the installer use the same check.
& (Join-Path $PSScriptRoot "assert-no-autodesk-assemblies.ps1") -Path $packageDir

# One zip per Revit year: everything in the package except the other years' binaries,
# so each user downloads only the build that matches their Revit.
foreach ($year in $years) {
    $stage = Join-Path $zipStageRoot $year
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Copy-Item -Path (Join-Path $packageDir "*") -Destination $stage -Recurse -Force
    foreach ($other in ($supportedYears | Where-Object { $_ -ne $year })) {
        Remove-WorkspaceDirectory (Join-Path $stage "bin\$other")
    }
    $distributionZip = Join-Path $releaseDir "aec-model-bridge-revit-$year-$Version.zip"
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $distributionZip -CompressionLevel Optimal
}
Remove-WorkspaceDirectory $zipStageRoot

New-Item -ItemType Directory -Path $mcpbStage -Force | Out-Null
$pythonPackage = Join-Path $repoRoot "packages\mcp-server-revit"
Copy-Item (Join-Path $pythonPackage "manifest.json") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "pyproject.toml") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "uv.lock") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "README.md") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "LICENSE") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "NOTICE") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "LICENSING.md") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "LICENSES") $mcpbStage -Recurse -Force
Copy-Item (Join-Path $pythonPackage "src") $mcpbStage -Recurse -Force

Get-ChildItem -Path $mcpbStage -Recurse -Directory -Filter "__pycache__" |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $mcpbStage -Recurse -Directory -Filter "*.egg-info" |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $mcpbStage -Recurse -File -Include "*.pyc", "*.pyo" |
    Remove-Item -Force

$mcpbZip = Join-Path $releaseDir "aec-model-bridge-$Version.zip"
$mcpbPath = Join-Path $releaseDir "aec-model-bridge-$Version.mcpb"
Compress-Archive -Path (Join-Path $mcpbStage "*") -DestinationPath $mcpbZip -CompressionLevel Optimal
Move-Item -LiteralPath $mcpbZip -Destination $mcpbPath

# Wheel file names use PEP 440 (1.3.0rc1); tags and VERSION use SemVer (1.3.0-rc.1).
$wheelVersion = $Version -replace '-(alpha|a)\.?(\d+)$', 'a$2' -replace '-(beta|b)\.?(\d+)$', 'b$2' -replace '-rc\.?(\d+)$', 'rc$1'
$wheel = Get-ChildItem -Path (Join-Path $packageDir "server") -Filter "aec_model_bridge-$wheelVersion-*.whl" |
    Select-Object -First 1
if (-not $wheel) {
    throw "Python wheel for version $Version was not produced."
}
Copy-Item -LiteralPath $wheel.FullName -Destination $releaseDir -Force

$mcpbSha = (Get-FileHash -LiteralPath $mcpbPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($UpdateServerMetadata) {
    $serverPath = Join-Path $repoRoot "server.json"
    $server = Get-Content -LiteralPath $serverPath -Raw | ConvertFrom-Json
    $server.version = $Version
    $server.packages[0].version = $Version
    $server.packages[0].identifier = "https://github.com/Sam-AEC/aec-model-bridge/releases/download/v$Version/aec-model-bridge-$Version.mcpb"
    $server.packages[0].fileSha256 = $mcpbSha
    $serverJson = ($server | ConvertTo-Json -Depth 20) + [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        $serverPath,
        $serverJson,
        [System.Text.UTF8Encoding]::new($false)
    )
}

if ($VSCodePackage) {
    Copy-Item -LiteralPath $vsixPath -Destination $releaseDir -Force
}

$checksums = Get-ChildItem -Path $releaseDir -File |
    Where-Object Name -ne "SHA256SUMS.txt" |
    Sort-Object Name |
    ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($_.Name)"
    }
$checksums | Set-Content -LiteralPath (Join-Path $releaseDir "SHA256SUMS.txt") -Encoding ascii

Remove-WorkspaceDirectory $mcpbStage

Write-Host "Release artifacts created in $releaseDir" -ForegroundColor Green
Get-ChildItem -Path $releaseDir -File | Select-Object Name, Length
