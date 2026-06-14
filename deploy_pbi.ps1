$pbiExternalToolsDir = 'C:\Program Files (x86)\Common Files\Microsoft Shared\Power BI Desktop\External Tools'
if (-not (Test-Path $pbiExternalToolsDir)) {
    New-Item -ItemType Directory -Force -Path $pbiExternalToolsDir | Out-Null
}
Copy-Item -Path 'c:\Users\sammo\OneDrive\Documenten\GitHub\Autodesk-Revit-MCP-Server\packages\powerbi-bridge-tool\AECModelBridge.pbitool_filled.json' -Destination (Join-Path $pbiExternalToolsDir 'AECModelBridge.pbitool.json') -Force
