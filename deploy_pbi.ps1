$pbiExternalToolsDir = 'C:\Program Files (x86)\Common Files\Microsoft Shared\Power BI Desktop\External Tools'
if (-not (Test-Path $pbiExternalToolsDir)) {
    New-Item -ItemType Directory -Force -Path $pbiExternalToolsDir | Out-Null
}

$exeDir = Join-Path $PSScriptRoot 'packages\powerbi-bridge-tool\bin\Release\net8.0-windows'
$template = Get-Content (Join-Path $PSScriptRoot 'packages\powerbi-bridge-tool\AECModelBridge.pbitool.json') -Raw
$template.Replace('%PBITOOL_PATH%', $exeDir) | Set-Content (Join-Path $pbiExternalToolsDir 'AECModelBridge.pbitool.json')
