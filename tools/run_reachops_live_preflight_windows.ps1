param(
    [string]$ProfileGroup = "BR",
    [string]$ProfileIds = "",
    [string]$CommentVideoUrl = "",
    [string]$TargetProfileUrl = "",
    [string]$DmProfileUrl = "",
    [string]$TargetUsername = "",
    [int]$Workers = 2,
    [int]$PerProfileLimit = 3,
    [int]$SwitchAttempts = 2,
    [int]$PerProfileHourLimit = 20,
    [int]$PerProfileVideoHourLimit = 5,
    [int]$PageTimeout = 45,
    [int]$ElementTimeout = 25
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    $dir = [System.IO.Path]::GetDirectoryName($fullPath)
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($fullPath, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Convert-StdoutJson {
    param(
        [string]$StdoutPath,
        [string]$OutputPath
    )
    $raw = Get-Content -Path $StdoutPath -Raw -Encoding UTF8
    $idx = $raw.LastIndexOf("{")
    while ($idx -ge 0) {
        $candidate = $raw.Substring($idx).Trim()
        try {
            $null = $candidate | ConvertFrom-Json -ErrorAction Stop
            Write-Utf8NoBom -Path $OutputPath -Content $candidate
            return
        } catch {
            if ($idx -eq 0) {
                break
            }
            $idx = $raw.LastIndexOf("{", $idx - 1)
        }
    }
    throw "No valid JSON payload found in $StdoutPath"
}

if (-not $TargetUsername) {
    if ($TargetProfileUrl -match "/@([^/?#]+)") {
        $TargetUsername = $Matches[1]
    } elseif ($DmProfileUrl -match "/@([^/?#]+)") {
        $TargetUsername = $Matches[1]
    }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$root = "reports\reachops_live_preflight\$stamp"
New-Item -ItemType Directory -Path $root -Force | Out-Null
$stdoutPath = Join-Path $root "live_preflight_stdout.json"
$payloadPath = Join-Path $root "live_preflight_payload.json"

Write-Host "[ReachOpsPreflight] Running no-submit live preflight." -ForegroundColor Cyan
Write-Host "[ReachOpsPreflight] No comment/follow/dm will be submitted." -ForegroundColor Yellow

$argsList = @(
    "tools\reachops_live_preflight.py",
    "--base-dir", (Join-Path $root "runtime"),
    "--workers", ([string][Math]::Max(1, $Workers)),
    "--per-profile-limit", ([string][Math]::Max(1, $PerProfileLimit)),
    "--switch-attempts", ([string][Math]::Max(1, $SwitchAttempts)),
    "--per-profile-hour-limit", ([string][Math]::Max(1, $PerProfileHourLimit)),
    "--per-profile-video-hour-limit", ([string][Math]::Max(1, $PerProfileVideoHourLimit)),
    "--page-timeout", ([string][Math]::Max(1, $PageTimeout)),
    "--element-timeout", ([string][Math]::Max(1, $ElementTimeout)),
    "--json"
)
if ($ProfileIds) {
    $argsList += @("--profile-ids", $ProfileIds)
}
if ($ProfileGroup) {
    $argsList += @("--group-name", $ProfileGroup)
}
if ($CommentVideoUrl) {
    $argsList += @("--video-url", $CommentVideoUrl)
}
if ($TargetProfileUrl) {
    $argsList += @("--profile-url", $TargetProfileUrl)
}
if ($DmProfileUrl) {
    $argsList += @("--dm-profile-url", $DmProfileUrl)
}
if ($TargetUsername) {
    $argsList += @("--target-username", $TargetUsername)
}

$output = & python @argsList 2>&1

$output | ForEach-Object { Write-Host $_ }

Write-Utf8NoBom -Path $stdoutPath -Content ($output -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $stdoutPath -OutputPath $payloadPath

Write-Host "REACHOPS_LIVE_PREFLIGHT_DIR=$root"
Write-Host "LIVE_PREFLIGHT_JSON=$payloadPath"
if ($LASTEXITCODE -ne 0) {
    throw "ReachOps live preflight blocked or failed with exit code $LASTEXITCODE. See $payloadPath"
}
