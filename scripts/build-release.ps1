param(
    [string]$Version = "1.0.1",
    [string]$RevitVersion = "2027",
    [switch]$UpdateServerMetadata
)

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$distRoot = Join-Path $repoRoot "dist"
$packageDir = Join-Path $distRoot "AECModelBridge"
$releaseDir = Join-Path $distRoot "release"
$mcpbStage = Join-Path $distRoot "mcpb-stage"

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
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

& (Join-Path $PSScriptRoot "package.ps1") -Version $Version -RevitVersion $RevitVersion
if ($LASTEXITCODE -ne 0) {
    throw "Distribution packaging failed with exit code $LASTEXITCODE"
}

$bridgeDll = Join-Path $packageDir "bin\$RevitVersion\AECModelBridge.dll"
if (-not (Test-Path -LiteralPath $bridgeDll)) {
    throw "Expected bridge assembly was not produced: $bridgeDll"
}

$prohibitedNames = @(
    "RevitAPI.dll",
    "RevitAPIUI.dll",
    "AdWindows.dll",
    "AdskLicensingSDK_*.dll"
)
$prohibitedFiles = foreach ($pattern in $prohibitedNames) {
    Get-ChildItem -Path $packageDir -Recurse -File -Filter $pattern -ErrorAction SilentlyContinue
}
if ($prohibitedFiles) {
    $paths = ($prohibitedFiles.FullName | Sort-Object -Unique) -join [Environment]::NewLine
    throw "Release contains Autodesk assemblies and cannot be published:$([Environment]::NewLine)$paths"
}

$distributionZip = Join-Path $releaseDir "aec-model-bridge-revit-$RevitVersion-$Version.zip"
Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $distributionZip -CompressionLevel Optimal

New-Item -ItemType Directory -Path $mcpbStage -Force | Out-Null
$pythonPackage = Join-Path $repoRoot "packages\mcp-server-revit"
Copy-Item (Join-Path $pythonPackage "manifest.json") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "pyproject.toml") $mcpbStage -Force
Copy-Item (Join-Path $pythonPackage "README.md") $mcpbStage -Force
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

$wheel = Get-ChildItem -Path (Join-Path $packageDir "server") -Filter "aec_model_bridge-$Version-*.whl" |
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
