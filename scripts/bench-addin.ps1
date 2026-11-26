<#
.SYNOPSIS
    Benchmarks the AEC Model Bridge Revit add-in with a fixed set of read-only calls (#285).

.DESCRIPTION
    Finds the running add-in through its registry file (%LOCALAPPDATA%\AECModelBridge\registry,
    newest revit-<pid>.json), calls each read tool -Iterations times in sequence, then sends
    -BurstSize list_levels calls at once to measure how many reads share a Revit turn (#287).
    Writes a JSON report with client-side timings and the add-in's /health "timings" block.

    Every call is read-only. revit.execute_python runs in mode "read" (rolled back by the add-in's
    read-mode guard); leave it out with -SkipPython.

    Run with Revit open on the canonical test model. Results are only meaningful from a live
    Revit session; record the Revit year and the hardware with the report.

.EXAMPLE
    .\scripts\bench-addin.ps1 -Iterations 20 -OutFile bench-2026.json
#>
param(
    [int]$Iterations = 20,
    [int]$BurstSize = 10,
    [string]$OutFile,
    [string]$RegistryFile,
    [int]$TimeoutSec = 60,
    [switch]$SkipPython
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

if ($Iterations -lt 1) { throw "Iterations must be at least 1." }
if ($BurstSize -lt 0) { throw "BurstSize must be 0 or more." }

if ([string]::IsNullOrWhiteSpace($RegistryFile)) {
    $registryDir = Join-Path $env:LOCALAPPDATA "AECModelBridge\registry"
    if (-not (Test-Path -LiteralPath $registryDir)) {
        throw "No registry folder at $registryDir. Start Revit with the add-in loaded."
    }
    $latest = Get-ChildItem -LiteralPath $registryDir -Filter "revit-*.json" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $latest) { throw "No revit-*.json in $registryDir. Start Revit with the add-in loaded." }
    $RegistryFile = $latest.FullName
}
$registry = Get-Content -LiteralPath $RegistryFile -Raw | ConvertFrom-Json
$endpoint = ([string]$registry.endpoint).TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($endpoint) -or [string]::IsNullOrWhiteSpace([string]$registry.session_token)) {
    throw "Registry file $RegistryFile has no endpoint or session_token."
}

$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
$client.DefaultRequestHeaders.Authorization =
    New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", [string]$registry.session_token)

function New-ExecuteContent([string]$Tool, [hashtable]$Payload) {
    $body = @{ request_id = [guid]::NewGuid().ToString(); tool = $Tool; payload = $Payload } | ConvertTo-Json -Depth 8 -Compress
    return New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, "application/json")
}

function Read-Status([string]$Text) {
    try { return ([string]($Text | ConvertFrom-Json).Status) } catch { return "" }
}

function Get-Percentile([double[]]$Sorted, [int]$Percent) {
    if ($Sorted.Count -eq 0) { return $null }
    $rank = [math]::Ceiling($Percent / 100.0 * $Sorted.Count)
    $index = [math]::Min($Sorted.Count - 1, [math]::Max(0, $rank - 1))
    return [math]::Round($Sorted[$index], 1)
}

function Invoke-Tool([string]$Tool, [hashtable]$Payload) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $response = $client.PostAsync("$endpoint/execute", (New-ExecuteContent $Tool $Payload)).GetAwaiter().GetResult()
    $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    $watch.Stop()
    return [pscustomobject]@{
        ms = $watch.Elapsed.TotalMilliseconds
        bytes = [System.Text.Encoding]::UTF8.GetByteCount($text)
        ok = ($response.IsSuccessStatusCode -and (Read-Status $text) -eq "ok")
    }
}

$tools = [ordered]@{
    "revit.health" = @{}
    "revit.get_context" = @{}
    "revit.get_document_info" = @{}
    "revit.list_levels" = @{}
    "revit.list_views" = @{}
    "revit.get_categories" = @{}
}
if (-not $SkipPython) {
    $tools["revit.execute_python"] = @{ script = "print(len(doc.Title))"; mode = "read" }
}

$results = [ordered]@{}
foreach ($tool in $tools.Keys) {
    Write-Host "Running $tool x $Iterations"
    $samples = @()
    for ($i = 0; $i -lt $Iterations; $i++) {
        $samples += Invoke-Tool $tool $tools[$tool]
    }
    $sorted = [double[]]($samples | ForEach-Object { $_.ms } | Sort-Object)
    $results[$tool] = [ordered]@{
        count = $samples.Count
        errors = @($samples | Where-Object { -not $_.ok }).Count
        first_ms = [math]::Round($samples[0].ms, 1)
        p50_ms = Get-Percentile $sorted 50
        p95_ms = Get-Percentile $sorted 95
        max_ms = [math]::Round($sorted[$sorted.Count - 1], 1)
        avg_bytes = [math]::Round((($samples | Measure-Object -Property bytes -Average).Average), 1)
    }
}

$burst = $null
if ($BurstSize -gt 0) {
    Write-Host "Sending $BurstSize revit.list_levels calls at once"
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $tasks = @()
    for ($i = 0; $i -lt $BurstSize; $i++) {
        $tasks += $client.PostAsync("$endpoint/execute", (New-ExecuteContent "revit.list_levels" @{}))
    }
    [System.Threading.Tasks.Task]::WaitAll([System.Threading.Tasks.Task[]]$tasks)
    $watch.Stop()
    $burstErrors = @($tasks | Where-Object {
        -not $_.Result.IsSuccessStatusCode -or
        (Read-Status ($_.Result.Content.ReadAsStringAsync().GetAwaiter().GetResult())) -ne "ok"
    }).Count
    $burst = [ordered]@{
        tool = "revit.list_levels"
        size = $BurstSize
        wall_ms = [math]::Round($watch.Elapsed.TotalMilliseconds, 1)
        errors = $burstErrors
    }
}

$healthText = $client.GetStringAsync("$endpoint/health").GetAwaiter().GetResult()
$health = $healthText | ConvertFrom-Json

$report = [ordered]@{
    generated_utc = (Get-Date).ToUniversalTime().ToString("o")
    host_version = $registry.host_version
    connector_version = $registry.connector_version
    active_document = $health.active_document
    iterations = $Iterations
    settings = [ordered]@{
        AEC_BRIDGE_TURN_BUDGET_MS = $env:AEC_BRIDGE_TURN_BUDGET_MS
        AEC_BRIDGE_FAST_WAKE = $env:AEC_BRIDGE_FAST_WAKE
        AEC_BRIDGE_PYTHON_RECYCLE_RUNS = $env:AEC_BRIDGE_PYTHON_RECYCLE_RUNS
        note = "These are this shell's values; the add-in reads its own environment when Revit starts."
    }
    client = $results
    burst = $burst
    addin_timings = $health.timings
}

if ([string]::IsNullOrWhiteSpace($OutFile)) {
    $OutFile = "bench-addin-$($registry.host_version)-$((Get-Date).ToString('yyyyMMdd-HHmmss')).json"
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutFile -Encoding UTF8
$client.Dispose()
Write-Host "Report written to $OutFile"
