param(
    [string]$DistPath
)

$ErrorActionPreference = "Stop"

if (-not $DistPath) {
    $DistPath = Join-Path $PSScriptRoot "..\dist\AECModelBridge"
}
$DistPath = [System.IO.Path]::GetFullPath($DistPath)
$pythonDir = Join-Path $DistPath "python"

Write-Host "Bundling portable Python runtime..." -ForegroundColor Cyan
Write-Host "  Target directory: $pythonDir" -ForegroundColor Gray

# Create Python directory
New-Item -ItemType Directory -Path $pythonDir -Force | Out-Null

$pythonExe = Join-Path $pythonDir "python.exe"
$testImport = if (Test-Path $pythonExe) {
    & "$pythonExe" -c "import revit_mcp_server" 2>&1
    $LASTEXITCODE -eq 0
} else { $false }

if (-not $testImport) {
    # 1. Download embeddable Python zip if not already present
    $zipPath = Join-Path $pythonDir "python-3.11.9-embed-amd64.zip"
    $downloadUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
    
    if (-not (Test-Path $pythonExe)) {
        Write-Host "  Downloading embeddable Python 3.11.9..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
        
        Write-Host "  Extracting Python zip..." -ForegroundColor Yellow
        Expand-Archive -Path $zipPath -DestinationPath $pythonDir -Force
        Remove-Item -LiteralPath $zipPath -Force
    }

    # 2. Modify .pth file to enable site-packages and 'import site'
    $pthFile = Get-ChildItem -Path $pythonDir -Filter "python311._pth" | Select-Object -First 1
    if ($pthFile) {
        Write-Host "  Configuring $($pthFile.Name)..." -ForegroundColor Yellow
        $content = Get-Content -LiteralPath $pthFile.FullName -Raw
        $content = $content -replace '#import site', 'import site'
        if ($content -notmatch 'Lib[/\\]site-packages') {
            $content += "`r`nLib/site-packages`r`n"
        }
        Set-Content -LiteralPath $pthFile.FullName -Value $content -Force
    }

    # Create Lib/site-packages folder
    $sitePackagesDir = Join-Path $pythonDir "Lib\site-packages"
    New-Item -ItemType Directory -Path $sitePackagesDir -Force | Out-Null

    # 3. Bootstrap pip using get-pip.py
    $getPipPath = Join-Path $pythonDir "get-pip.py"
    Write-Host "  Downloading get-pip.py..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath -UseBasicParsing

    Write-Host "  Bootstrapping pip into embedded Python..." -ForegroundColor Yellow
    & "$pythonExe" "$getPipPath" --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install pip into embedded Python."
        exit $LASTEXITCODE
    }
    Remove-Item -LiteralPath $getPipPath -Force

    # 4. Install revit_mcp_server package and dependencies
    $mcpServerPackage = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\packages\mcp-server-revit"))
    Write-Host "  Installing revit_mcp_server from $mcpServerPackage..." -ForegroundColor Yellow
    & "$pythonExe" -m pip install --no-warn-script-location "$mcpServerPackage"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install mcp-server-revit into embedded Python."
        exit $LASTEXITCODE
    }
}

Write-Host "  Verifying bundled Python runtime..." -ForegroundColor Yellow
& "$pythonExe" -c "import revit_mcp_server; print('revit_mcp_server imported successfully')"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Portable Python runtime bundled successfully at: $pythonDir" -ForegroundColor Green
} else {
    Write-Error "Failed to verify revit_mcp_server in bundled Python."
    exit 1
}
