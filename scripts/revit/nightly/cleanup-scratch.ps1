<#
.SYNOPSIS
    Stops the Revit that prepare-scratch.ps1 started and deletes the scratch copy (#295).

.DESCRIPTION
    Kills only the given process id, and only when it is a Revit process, without saving. Deletes
    only a file whose name contains "-scratch-". Safe to run when either is already gone.

    UNVERIFIED: not run against a live Revit.
#>
param(
    [int]$ProcessId,
    [string]$ScratchFile
)

$ErrorActionPreference = "Continue"

if ($ProcessId -gt 0) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -eq "Revit") { Stop-Process -Id $ProcessId -Force }
}
if ($ScratchFile -and ([IO.Path]::GetFileName($ScratchFile) -like "*-scratch-*.rvt") -and (Test-Path -LiteralPath $ScratchFile)) {
    Start-Sleep -Seconds 3
    Remove-Item -LiteralPath $ScratchFile -Force -ErrorAction SilentlyContinue
}
exit 0
