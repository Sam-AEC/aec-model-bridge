param(
    [string]$Repository = $(if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { "Sam-AEC/aec-model-bridge" }),
    [string]$Token = $(if ($env:GH_TOKEN) { $env:GH_TOKEN } else { $env:GITHUB_TOKEN }),
    [string]$MetricsPath = "metrics/downloads.json",
    [string]$ChartPath = "assets/downloads-history.svg",
    [string]$BadgeDirectory = "assets"
)

$ErrorActionPreference = "Stop"

function ConvertTo-XmlText {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return [System.Security.SecurityElement]::Escape([string]$Value)
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $directory = Split-Path -Parent $Path
    if ($directory) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    [System.IO.File]::WriteAllText(
        [System.IO.Path]::GetFullPath($Path),
        $Content,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Write-Badge {
    param(
        [string]$Path,
        [string]$Label,
        [string]$Message,
        [string]$Color
    )

    $labelWidth = [Math]::Max(92, ($Label.Length * 7) + 18)
    $messageWidth = [Math]::Max(48, ($Message.Length * 7) + 18)
    $width = $labelWidth + $messageWidth
    $labelX = [Math]::Round($labelWidth / 2)
    $messageX = $labelWidth + [Math]::Round($messageWidth / 2)
    $labelText = ConvertTo-XmlText $Label
    $messageText = ConvertTo-XmlText $Message

    $svg = @"
<svg xmlns="http://www.w3.org/2000/svg" width="$width" height="20" role="img" aria-label="${labelText}: ${messageText}">
  <title>${labelText}: ${messageText}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
    <stop offset=".1" stop-color="#aaa" stop-opacity=".1"/>
    <stop offset=".9" stop-color="#000" stop-opacity=".3"/>
    <stop offset="1" stop-color="#000" stop-opacity=".5"/>
  </linearGradient>
  <clipPath id="r"><rect width="$width" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="$labelWidth" height="20" fill="#555"/>
    <rect x="$labelWidth" width="$messageWidth" height="20" fill="$Color"/>
    <rect width="$width" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">
    <text x="$labelX" y="15" fill="#010101" fill-opacity=".3">${labelText}</text>
    <text x="$labelX" y="14">${labelText}</text>
    <text x="$messageX" y="15" fill="#010101" fill-opacity=".3">${messageText}</text>
    <text x="$messageX" y="14">${messageText}</text>
  </g>
</svg>
"@

    Write-Utf8NoBom -Path $Path -Content ($svg.Trim() + [Environment]::NewLine)
}

$headers = @{
    Accept = "application/vnd.github+json"
    "User-Agent" = "aec-model-bridge-download-metrics"
    "X-GitHub-Api-Version" = "2022-11-28"
}
if ($Token) {
    $headers.Authorization = "Bearer $Token"
}

$releases = @()
$page = 1
do {
    $uri = "https://api.github.com/repos/$Repository/releases?per_page=100&page=$page"
    $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
    if ($null -eq $response) {
        $response = @()
    }
    $releases += $response
    $page++
} while ($response.Count -eq 100)

$publishedReleases = @(
    $releases |
        Where-Object { -not $_.draft } |
        Sort-Object { [DateTimeOffset]$_.published_at } -Descending
)

$releaseMetrics = @(
    foreach ($release in $publishedReleases) {
        $downloads = [int](($release.assets | Measure-Object -Property download_count -Sum).Sum)
        [pscustomobject][ordered]@{
            tag = [string]$release.tag_name
            published_at = ([DateTimeOffset]$release.published_at).ToUniversalTime().ToString("o")
            prerelease = [bool]$release.prerelease
            downloads = $downloads
        }
    }
)

$totalDownloads = [int](($releaseMetrics | Measure-Object -Property downloads -Sum).Sum)
$snapshotDate = [DateTimeOffset]::UtcNow.Date
$today = $snapshotDate.ToString("yyyy-MM-dd")
$history = @()

if (Test-Path -LiteralPath $MetricsPath) {
    $existing = Get-Content -LiteralPath $MetricsPath -Raw | ConvertFrom-Json
    if ($existing.history) {
        $history = @(
            $existing.history |
                Where-Object { $_.date -ne $today } |
                ForEach-Object {
                    [pscustomobject][ordered]@{
                        date = [string]$_.date
                        total = [int]$_.total
                    }
                }
        )
    }
}

$history += [pscustomobject][ordered]@{
    date = $today
    total = $totalDownloads
}
$history = @(
    $history |
        Sort-Object { [DateTime]$_.date } |
        Select-Object -Last 180
)

function Get-DownloadDelta {
    param([int]$Days)

    $targetDate = $snapshotDate.AddDays(-$Days)
    $baseline = $history |
        Where-Object { [DateTimeOffset]::Parse($_.date) -le $targetDate } |
        Select-Object -Last 1

    if ($null -eq $baseline) {
        return $null
    }

    return [int]($totalDownloads - [int]$baseline.total)
}

$delta7 = Get-DownloadDelta -Days 7
$delta30 = Get-DownloadDelta -Days 30
$latestRelease = $releaseMetrics | Where-Object { -not $_.prerelease } | Select-Object -First 1
$latestDownloads = if ($latestRelease) { [int]$latestRelease.downloads } else { 0 }

$metrics = [ordered]@{
    schema_version = 1
    repository = $Repository
    updated_at = [DateTimeOffset]::UtcNow.ToString("o")
    totals = [ordered]@{
        all_releases = $totalDownloads
        latest_release = $latestDownloads
        last_7_days = $delta7
        last_30_days = $delta30
    }
    releases = $releaseMetrics
    history = $history
}

$metricsJson = ($metrics | ConvertTo-Json -Depth 10) + [Environment]::NewLine
Write-Utf8NoBom -Path $MetricsPath -Content $metricsJson

$delta7Label = if ($null -eq $delta7) { "tracking" } else { "+$delta7" }
$delta30Label = if ($null -eq $delta30) { "tracking" } else { "+$delta30" }
Write-Badge -Path (Join-Path $BadgeDirectory "downloads-total.svg") -Label "release downloads" -Message ([string]$totalDownloads) -Color "#2563EB"
Write-Badge -Path (Join-Path $BadgeDirectory "downloads-7d.svg") -Label "downloads 7d" -Message $delta7Label -Color "#0F766E"
Write-Badge -Path (Join-Path $BadgeDirectory "downloads-30d.svg") -Label "downloads 30d" -Message $delta30Label -Color "#7C3AED"

$chartWidth = 920
$chartHeight = 470
$releaseChartX = 46
$releaseChartY = 190
$releaseChartWidth = 360
$trendChartX = 500
$trendChartY = 190
$trendChartWidth = 374
$chartPlotHeight = 205
$topReleases = @($releaseMetrics | Select-Object -First 5)
$maxReleaseDownloads = [Math]::Max(1, [int](($topReleases | Measure-Object -Property downloads -Maximum).Maximum))
$svgLines = [System.Collections.Generic.List[string]]::new()
$svgLines.Add('<svg xmlns="http://www.w3.org/2000/svg" width="920" height="470" viewBox="0 0 920 470" role="img" aria-labelledby="title desc">')
$svgLines.Add('  <title id="title">AEC Model Bridge release download history</title>')
$svgLines.Add('  <desc id="desc">Current GitHub release downloads by release and cumulative daily history.</desc>')
$svgLines.Add('  <rect width="920" height="470" rx="14" fill="#0F172A"/>')
$svgLines.Add('  <text x="42" y="48" fill="#F8FAFC" font-family="Segoe UI,Arial,sans-serif" font-size="24" font-weight="600">GitHub release downloads</text>')
$svgLines.Add("  <text x=`"42`" y=`"75`" fill=`"#94A3B8`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"13`">Updated $(ConvertTo-XmlText $today) UTC. Source: GitHub release asset API.</text>")

$cards = @(
    @{ X = 42; Label = "TOTAL"; Value = [string]$totalDownloads; Color = "#60A5FA" },
    @{ X = 258; Label = "LAST 7 DAYS"; Value = $delta7Label; Color = "#2DD4BF" },
    @{ X = 474; Label = "LAST 30 DAYS"; Value = $delta30Label; Color = "#C4B5FD" },
    @{ X = 690; Label = "LATEST RELEASE"; Value = [string]$latestDownloads; Color = "#FBBF24" }
)
foreach ($card in $cards) {
    $svgLines.Add("  <rect x=`"$($card.X)`" y=`"98`" width=`"188`" height=`"66`" rx=`"8`" fill=`"#1E293B`" stroke=`"#334155`"/>")
    $svgLines.Add("  <text x=`"$($card.X + 16)`" y=`"121`" fill=`"#94A3B8`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"11`" font-weight=`"600`">$($card.Label)</text>")
    $svgLines.Add("  <text x=`"$($card.X + 16)`" y=`"151`" fill=`"$($card.Color)`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"24`" font-weight=`"700`">$($card.Value)</text>")
}

$svgLines.Add('  <text x="42" y="188" fill="#E2E8F0" font-family="Segoe UI,Arial,sans-serif" font-size="14" font-weight="600">Downloads by release</text>')
if ($topReleases.Count -eq 0) {
    $svgLines.Add('  <text x="46" y="225" fill="#94A3B8" font-family="Segoe UI,Arial,sans-serif" font-size="13">No published releases found.</text>')
}
else {
    for ($i = 0; $i -lt $topReleases.Count; $i++) {
        $release = $topReleases[$i]
        $y = $releaseChartY + ($i * 39)
        $barWidth = [Math]::Round(($release.downloads / $maxReleaseDownloads) * $releaseChartWidth)
        if ($release.downloads -gt 0) {
            $barWidth = [Math]::Max(4, $barWidth)
        }
        $tag = ConvertTo-XmlText $release.tag
        $svgLines.Add("  <text x=`"$releaseChartX`" y=`"$($y + 14)`" fill=`"#CBD5E1`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"12`">$tag</text>")
        $svgLines.Add("  <rect x=`"$releaseChartX`" y=`"$($y + 20)`" width=`"$releaseChartWidth`" height=`"10`" rx=`"5`" fill=`"#1E293B`"/>")
        $svgLines.Add("  <rect x=`"$releaseChartX`" y=`"$($y + 20)`" width=`"$barWidth`" height=`"10`" rx=`"5`" fill=`"#3B82F6`"/>")
        $svgLines.Add("  <text x=`"$($releaseChartX + $releaseChartWidth + 10)`" y=`"$($y + 29)`" fill=`"#F8FAFC`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"12`" font-weight=`"600`">$($release.downloads)</text>")
    }
}

$svgLines.Add('  <text x="496" y="188" fill="#E2E8F0" font-family="Segoe UI,Arial,sans-serif" font-size="14" font-weight="600">Cumulative daily history</text>')
$svgLines.Add("  <rect x=`"$trendChartX`" y=`"$trendChartY`" width=`"$trendChartWidth`" height=`"$chartPlotHeight`" rx=`"8`" fill=`"#111C2F`" stroke=`"#334155`"/>")
if ($history.Count -lt 2) {
    $trackingDate = [DateTime]::Parse($history[0].date).ToString("d MMM yyyy")
    $svgLines.Add('  <text x="687" y="274" text-anchor="middle" fill="#E2E8F0" font-family="Segoe UI,Arial,sans-serif" font-size="15" font-weight="600">Daily tracking has started</text>')
    $svgLines.Add("  <text x=`"687`" y=`"301`" text-anchor=`"middle`" fill=`"#94A3B8`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"12`">First snapshot: $(ConvertTo-XmlText $trackingDate)</text>")
    $svgLines.Add('  <text x="687" y="325" text-anchor="middle" fill="#94A3B8" font-family="Segoe UI,Arial,sans-serif" font-size="12">7-day and 30-day changes populate automatically.</text>')
}
else {
    $historyValues = @($history | ForEach-Object { [int]$_.total })
    $minValue = [int](($historyValues | Measure-Object -Minimum).Minimum)
    $maxValue = [int](($historyValues | Measure-Object -Maximum).Maximum)
    if ($maxValue -eq $minValue) {
        $maxValue = $minValue + 1
    }

    $points = @()
    for ($i = 0; $i -lt $history.Count; $i++) {
        $x = $trendChartX + 12 + (($i / ($history.Count - 1)) * ($trendChartWidth - 24))
        $normalized = ([int]$history[$i].total - $minValue) / ($maxValue - $minValue)
        $y = $trendChartY + $chartPlotHeight - 16 - ($normalized * ($chartPlotHeight - 32))
        $points += "$([Math]::Round($x, 1)),$([Math]::Round($y, 1))"
    }
    $svgLines.Add("  <polyline points=`"$($points -join ' ')`" fill=`"none`" stroke=`"#2DD4BF`" stroke-width=`"3`" stroke-linecap=`"round`" stroke-linejoin=`"round`"/>")
    $svgLines.Add("  <text x=`"$($trendChartX + 12)`" y=`"$($trendChartY + $chartPlotHeight - 4)`" fill=`"#64748B`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"10`">$(ConvertTo-XmlText $history[0].date)</text>")
    $svgLines.Add("  <text x=`"$($trendChartX + $trendChartWidth - 12)`" y=`"$($trendChartY + $chartPlotHeight - 4)`" text-anchor=`"end`" fill=`"#64748B`" font-family=`"Segoe UI,Arial,sans-serif`" font-size=`"10`">$(ConvertTo-XmlText $history[-1].date)</text>")
}

$svgLines.Add('  <text x="42" y="441" fill="#64748B" font-family="Segoe UI,Arial,sans-serif" font-size="11">Counts include GitHub release assets only. Source archives and repository clones are not release downloads.</text>')
$svgLines.Add('</svg>')
Write-Utf8NoBom -Path $ChartPath -Content (($svgLines -join [Environment]::NewLine) + [Environment]::NewLine)

Write-Host "Updated download metrics for $Repository"
Write-Host "Total downloads: $totalDownloads"
Write-Host "7-day change: $delta7Label"
Write-Host "30-day change: $delta30Label"
