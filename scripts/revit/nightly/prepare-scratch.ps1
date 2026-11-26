<#
.SYNOPSIS
    Copies the canonical model to a scratch file and opens it in a fresh Revit (#295).

.DESCRIPTION
    For the self-hosted nightly live test only. Refuses to run when a Revit is already open, so
    the nightly never touches a model a person is working on. The copy has "scratch" in its
    name, which the harness identity check requires. Writes pid, title and scratch_file to
    GITHUB_OUTPUT when it is set, and to the console otherwise.

    UNVERIFIED: not run against a live Revit. Starting Revit with a file path, the registry
    file name and the /health shape follow scripts/bench-addin.ps1 and are not yet observed here.
#>
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$RevitExe,
    [string]$ScratchDir = (Join-Path $env:RUNNER_TEMP "aec-nightly-scratch"),
    [int]$TimeoutSec = 300
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Source -PathType Leaf) -or [IO.Path]::GetExtension($Source) -ne ".rvt") {
    throw "Source must be an existing .rvt file."
}
if (-not (Test-Path -LiteralPath $RevitExe -PathType Leaf)) { throw "RevitExe does not exist." }
if (@(Get-Process -Name Revit -ErrorAction SilentlyContinue).Count -gt 0) {
    throw "A Revit is already running. The nightly run needs a machine with no open Revit."
}

New-Item -ItemType Directory -Force -Path $ScratchDir | Out-Null
$stem = "{0}-scratch-{1}" -f [IO.Path]::GetFileNameWithoutExtension($Source), (Get-Date -Format "yyyyMMdd-HHmmss")
$scratch = Join-Path $ScratchDir "$stem.rvt"
Copy-Item -LiteralPath $Source -Destination $scratch

$process = Start-Process -FilePath $RevitExe -ArgumentList ('"{0}"' -f $scratch) -PassThru
$registry = Join-Path $env:LOCALAPPDATA ("AECModelBridge\registry\revit-{0}.json" -f $process.Id)
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while (-not (Test-Path -LiteralPath $registry)) {
    if ($process.HasExited) { throw "Revit exited before the add-in registered." }
    if ((Get-Date) -gt $deadline) { throw "The add-in did not register within $TimeoutSec s." }
    Start-Sleep -Seconds 5
}

# The add-in is up; wait until it reports the scratch copy as the active document.
Add-Type -AssemblyName System.Net.Http
$info = Get-Content -LiteralPath $registry -Raw | ConvertFrom-Json
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(20)
$client.DefaultRequestHeaders.Authorization =
    New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", [string]$info.session_token)
$ready = $false
while (-not $ready) {
    if ($process.HasExited) { throw "Revit exited while opening the scratch copy." }
    if ((Get-Date) -gt $deadline) { throw "Revit did not report the scratch copy within $TimeoutSec s." }
    try {
        $health = $client.GetStringAsync(([string]$info.endpoint).TrimEnd("/") + "/health").GetAwaiter().GetResult() | ConvertFrom-Json
        $ready = ((($health.active_document | ConvertTo-Json -Compress -Depth 4) -like "*$stem*"))
    } catch { $ready = $false }
    if (-not $ready) { Start-Sleep -Seconds 5 }
}
$client.Dispose()

$lines = @("pid=$($process.Id)", "title=$stem", "scratch_file=$scratch")
if ($env:GITHUB_OUTPUT) { $lines | Add-Content -LiteralPath $env:GITHUB_OUTPUT -Encoding utf8 } else { $lines }
