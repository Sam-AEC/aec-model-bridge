param(
    [string]$PythonPath = "C:\ProgramData\AECModelBridge\python\python.exe"
)

$ErrorActionPreference = "Stop"

Write-Host "Configuring MCP clients for AEC Model Bridge..." -ForegroundColor Cyan
Write-Host "  Python binary: $PythonPath" -ForegroundColor Gray

# Define MCP server configurations
$serverConfigStdio = [ordered]@{
    command = $PythonPath
    args    = @("-m", "revit_mcp_server.mcp_server")
    env     = [ordered]@{
        MCP_REVIT_MODE       = "bridge"
        MCP_REVIT_BRIDGE_URL = "http://127.0.0.1:3000"
    }
}

$serverConfigVSCode = [ordered]@{
    type    = "stdio"
    command = $PythonPath
    args    = @("-m", "revit_mcp_server.mcp_server")
    env     = [ordered]@{
        MCP_REVIT_MODE       = "bridge"
        MCP_REVIT_BRIDGE_URL = "http://127.0.0.1:3000"
    }
}

# 1. Configure Claude Desktop (%APPDATA%\Claude\claude_desktop_config.json)
$claudeDir = Join-Path $env:APPDATA "Claude"
$claudeConfigFile = Join-Path $claudeDir "claude_desktop_config.json"

try {
    if (-not (Test-Path $claudeDir)) {
        New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null
    }

    $claudeConfig = [ordered]@{ mcpServers = [ordered]@{} }
    if (Test-Path $claudeConfigFile) {
        $raw = Get-Content -LiteralPath $claudeConfigFile -Raw -ErrorAction SilentlyContinue
        if ($raw) {
            $parsed = $raw | ConvertFrom-Json
            if ($parsed) {
                if ($parsed.mcpServers) {
                    $mcpServersObj = [ordered]@{}
                    foreach ($prop in $parsed.mcpServers.PSObject.Properties) {
                        $mcpServersObj[$prop.Name] = $prop.Value
                    }
                    $claudeConfig["mcpServers"] = $mcpServersObj
                }
                foreach ($prop in $parsed.PSObject.Properties) {
                    if ($prop.Name -ne "mcpServers") {
                        $claudeConfig[$prop.Name] = $prop.Value
                    }
                }
            }
        }
    }

    $claudeConfig["mcpServers"]["aec-model-bridge"] = $serverConfigStdio
    $claudeConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $claudeConfigFile -Force
    Write-Host "  Configured Claude Desktop: $claudeConfigFile" -ForegroundColor Green
}
catch {
    Write-Warning "Failed to configure Claude Desktop: $_"
}

# 2. Configure VS Code User Level
$codeUserDir = Join-Path $env:APPDATA "Code\User"
if (Test-Path $codeUserDir) {
    # Path A: globalStorage\ms-vscode.vscode-mcp\mcp.json
    $vscMcpDir = Join-Path $codeUserDir "globalStorage\ms-vscode.vscode-mcp"
    New-Item -ItemType Directory -Path $vscMcpDir -Force | Out-Null
    $vscMcpFile = Join-Path $vscMcpDir "mcp.json"

    try {
        $vscConfig = [ordered]@{ servers = [ordered]@{} }
        if (Test-Path $vscMcpFile) {
            $raw = Get-Content -LiteralPath $vscMcpFile -Raw -ErrorAction SilentlyContinue
            if ($raw) {
                $parsed = $raw | ConvertFrom-Json
                if ($parsed -and $parsed.servers) {
                    $serversObj = [ordered]@{}
                    foreach ($prop in $parsed.servers.PSObject.Properties) {
                        $serversObj[$prop.Name] = $prop.Value
                    }
                    $vscConfig["servers"] = $serversObj
                }
            }
        }
        $vscConfig["servers"]["aec-model-bridge"] = $serverConfigVSCode
        $vscConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $vscMcpFile -Force
        Write-Host "  Configured VS Code MCP file: $vscMcpFile" -ForegroundColor Green
    }
    catch {
        Write-Warning "Failed to update VS Code mcp.json: $_"
    }

    # Path B: %APPDATA%\Code\User\mcp.json
    $userMcpFile = Join-Path $codeUserDir "mcp.json"
    try {
        $userConfig = [ordered]@{ servers = [ordered]@{} }
        if (Test-Path $userMcpFile) {
            $raw = Get-Content -LiteralPath $userMcpFile -Raw -ErrorAction SilentlyContinue
            if ($raw) {
                $parsed = $raw | ConvertFrom-Json
                if ($parsed -and $parsed.servers) {
                    $serversObj = [ordered]@{}
                    foreach ($prop in $parsed.servers.PSObject.Properties) {
                        $serversObj[$prop.Name] = $prop.Value
                    }
                    $userConfig["servers"] = $serversObj
                }
            }
        }
        $userConfig["servers"]["aec-model-bridge"] = $serverConfigVSCode
        $userConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $userMcpFile -Force
        Write-Host "  Configured VS Code User mcp.json: $userMcpFile" -ForegroundColor Green
    }
    catch {
        Write-Warning "Failed to update user mcp.json: $_"
    }

    # Path C: %APPDATA%\Code\User\settings.json ("mcp.servers")
    $settingsFile = Join-Path $codeUserDir "settings.json"
    try {
        $settingsConfig = [ordered]@{}
        if (Test-Path $settingsFile) {
            $raw = Get-Content -LiteralPath $settingsFile -Raw -ErrorAction SilentlyContinue
            if ($raw) {
                $cleanRaw = ($raw -split "`r?`n" | Where-Object { $_ -notmatch '^\s*//' }) -join "`n"
                $parsed = $cleanRaw | ConvertFrom-Json
                if ($parsed) {
                    foreach ($prop in $parsed.PSObject.Properties) {
                        $settingsConfig[$prop.Name] = $prop.Value
                    }
                }
            }
        }
        $mcpServersObj = [ordered]@{}
        if ($settingsConfig.Contains("mcp.servers") -and $settingsConfig["mcp.servers"]) {
            foreach ($prop in $settingsConfig["mcp.servers"].PSObject.Properties) {
                $mcpServersObj[$prop.Name] = $prop.Value
            }
        }
        $mcpServersObj["aec-model-bridge"] = $serverConfigStdio
        $settingsConfig["mcp.servers"] = $mcpServersObj
        $settingsConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $settingsFile -Force
        Write-Host "  Configured VS Code settings.json: $settingsFile" -ForegroundColor Green
    }
    catch {
        Write-Warning "Failed to update VS Code settings.json: $_"
    }
} else {
    Write-Host "  VS Code user directory not found ($codeUserDir) - skipping VS Code config" -ForegroundColor Gray
}

Write-Host "MCP client configuration complete!" -ForegroundColor Green
