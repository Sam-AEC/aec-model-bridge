param(
    [string]$PythonPath = "C:\ProgramData\AECModelBridge\python\python.exe"
)

$ErrorActionPreference = "Stop"

Write-Host "Configuring MCP clients for AEC Model Bridge..." -ForegroundColor Cyan
Write-Host "  Python binary: $PythonPath" -ForegroundColor Gray

function New-ServerConfig {
    param(
        [string]$HostVersion,
        [switch]$VSCode
    )

    $envConfig = [ordered]@{
        MCP_REVIT_MODE = "bridge"
    }
    if ($HostVersion) {
        $envConfig["MCP_REVIT_HOST_VERSION"] = $HostVersion
    }

    $config = [ordered]@{
        command = $PythonPath
        args    = @("-m", "revit_mcp_server.mcp_server")
        env     = $envConfig
    }
    if ($VSCode) {
        $config = [ordered]@{
            type    = "stdio"
            command = $PythonPath
            args    = @("-m", "revit_mcp_server.mcp_server")
            env     = $envConfig
        }
    }
    return $config
}

function Add-RevitServers {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Servers,
        [switch]$VSCode
    )

    $Servers["aec-model-bridge"] = New-ServerConfig -VSCode:$VSCode
    foreach ($year in @("2024", "2025", "2026", "2027")) {
        $Servers["aec-model-bridge-revit-$year"] = New-ServerConfig -HostVersion $year -VSCode:$VSCode
    }
}

# Writes a config file safely: skips the write when nothing changes, keeps a timestamped
# backup of the existing file next to it, writes UTF-8 without BOM, and replaces the file
# in one step (temp file + move) so a crash never leaves a half-written config.
function Write-ConfigFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Object
    )

    # Depth 100 so nested values in an existing file (for example VS Code settings) are not flattened.
    $json = ($Object | ConvertTo-Json -Depth 100) + [Environment]::NewLine
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)

    if (Test-Path -LiteralPath $Path) {
        $current = [System.IO.File]::ReadAllText($Path)
        if ($current -eq $json) {
            Write-Host "  Already up to date: $Path" -ForegroundColor Gray
            return
        }
        $backup = "$Path.aec-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $Path -Destination $backup -Force
        Write-Host "  Backup: $backup" -ForegroundColor Gray
    }

    $temp = "$Path.aec-tmp"
    try {
        [System.IO.File]::WriteAllText($temp, $json, $utf8NoBom)
        Move-Item -LiteralPath $temp -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    }
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    Write-Warning "Python not found at $PythonPath. No client configuration was changed."
    exit 1
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

    Add-RevitServers -Servers $claudeConfig["mcpServers"]
    Write-ConfigFile -Path $claudeConfigFile -Object $claudeConfig
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
        Add-RevitServers -Servers $vscConfig["servers"] -VSCode
        Write-ConfigFile -Path $vscMcpFile -Object $vscConfig
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
        Add-RevitServers -Servers $userConfig["servers"] -VSCode
        Write-ConfigFile -Path $userMcpFile -Object $userConfig
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
                # settings.json is JSON with comments. Rewriting it would drop the comments,
                # so leave a commented file alone (the other MCP files above are enough).
                if ($cleanRaw -ne $raw -or $raw -match '/\*') {
                    throw "settings.json contains comments; not rewriting it (add the servers by hand if you need them there)."
                }
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
        Add-RevitServers -Servers $mcpServersObj
        $settingsConfig["mcp.servers"] = $mcpServersObj
        Write-ConfigFile -Path $settingsFile -Object $settingsConfig
        Write-Host "  Configured VS Code settings.json: $settingsFile" -ForegroundColor Green
    }
    catch {
        Write-Warning "Failed to update VS Code settings.json: $_"
    }
} else {
    Write-Host "  VS Code user directory not found ($codeUserDir) - skipping VS Code config" -ForegroundColor Gray
}

Write-Host "MCP client configuration complete!" -ForegroundColor Green
