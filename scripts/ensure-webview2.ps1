$ErrorActionPreference = "Stop"

Write-Host "Checking WebView2 Runtime status..." -ForegroundColor Cyan

function Test-WebView2Installed {
    # 1. Fast path wildcard checks
    $candidatePatterns = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\*\msedgewebview2.exe",
        "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
        "${env:ProgramFiles(x86)}\Microsoft\EdgeCore\*\msedgewebview2.exe",
        "${env:ProgramFiles}\Microsoft\Edge\Application\*\msedgewebview2.exe",
        "${env:ProgramFiles}\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe"
    )
    foreach ($pattern in $candidatePatterns) {
        $matches = Get-Item -Path $pattern -ErrorAction SilentlyContinue
        if ($matches) {
            return $true
        }
    }

    # 2. Registry checks
    $guid = "{F3C4CD00-EF15-42AA-9D7A-456402B44F24}"
    $regPaths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid"
    )
    foreach ($reg in $regPaths) {
        if (Test-Path -Path $reg) {
            $pv = (Get-ItemProperty -Path $reg -Name "pv" -ErrorAction SilentlyContinue).pv
            if ($pv -and $pv -ne "0.0.0.0") {
                return $true
            }
        }
    }

    return $false
}

if (Test-WebView2Installed) {
    Write-Host "  WebView2 Runtime is present." -ForegroundColor Green
    exit 0
}

Write-Host "  WebView2 Runtime not found. Triggering Microsoft Evergreen Bootstrapper..." -ForegroundColor Yellow

$setupUrl = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
$setupPath = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"

try {
    Write-Host "  Downloading MicrosoftEdgeWebview2Setup.exe..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $setupUrl -OutFile $setupPath -UseBasicParsing
    
    Write-Host "  Running silent WebView2 installation..." -ForegroundColor Yellow
    $process = Start-Process -FilePath $setupPath -ArgumentList "/silent /install" -Wait -PassThru
    if ($process.ExitCode -eq 0 -or $process.ExitCode -eq -2147219416) {
        Write-Host "  WebView2 Runtime installed/up to date." -ForegroundColor Green
    } else {
        Write-Warning "WebView2 installer exited with code $($process.ExitCode)"
    }
}
catch {
    Write-Warning "Failed to download or run WebView2 installer: $_"
}
finally {
    if (Test-Path $setupPath) {
        Remove-Item -LiteralPath $setupPath -Force -ErrorAction SilentlyContinue
    }
}
