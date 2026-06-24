param(
    [string]$ProfileGroup = "BR",
    [string]$ProfileIds = "",
    [string]$CommentVideoUrl = "",
    [string]$TargetProfileUrl = "",
    [string]$TargetUsername = "",
    [string]$ActivationStatusPath = "",
    [int]$Limit = 3,
    [string]$AllowPressureSubmit = "",
    [switch]$ConfirmAuthorizedTargets
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

if (-not $ProfileIds) {
    throw "ProfileIds is required. Example: -ProfileIds '123,456'"
}
if (-not $CommentVideoUrl) {
    throw "CommentVideoUrl is required. Example: -CommentVideoUrl 'https://www.tiktok.com/@creator/video/123'"
}
if (-not $TargetProfileUrl) {
    throw "TargetProfileUrl is required. Example: -TargetProfileUrl 'https://www.tiktok.com/@buyer_one'"
}
if (-not $TargetUsername) {
    if ($TargetProfileUrl -match "/@([^/?#]+)") {
        $TargetUsername = $Matches[1]
    } else {
        throw "TargetUsername is required when TargetProfileUrl does not contain /@username."
    }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$root = "reports\reachops_live_readiness\$stamp"
New-Item -ItemType Directory -Path $root -Force | Out-Null
$stdoutPath = Join-Path $root "live_readiness_stdout.json"
$payloadPath = Join-Path $root "live_readiness_payload.json"

Write-Host "[ReachOpsReadiness] Checking live-submit readiness only." -ForegroundColor Cyan
Write-Host "[ReachOpsReadiness] No browser will be opened. No comment/follow/dm will be submitted." -ForegroundColor Yellow

$argsList = @(
    "tools\reachops_live_readiness.py",
    "--profile-ids", $ProfileIds,
    "--group-name", $ProfileGroup,
    "--video-url", $CommentVideoUrl,
    "--follow-profile-url", $TargetProfileUrl,
    "--dm-profile-url", $TargetProfileUrl,
    "--target-username", $TargetUsername,
    "--limit", "$Limit",
    "--json"
)
if ($ConfirmAuthorizedTargets) {
    $argsList += @("--confirm-authorized-targets", "YES")
}
if ($AllowPressureSubmit) {
    $argsList += @("--allow-pressure-submit", $AllowPressureSubmit)
}
if ($ActivationStatusPath) {
    $argsList += @("--activation-status-path", $ActivationStatusPath)
}

$output = & python @argsList 2>&1
$output | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $stdoutPath -Content ($output -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $stdoutPath -OutputPath $payloadPath

$payload = Get-Content -Path $payloadPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
Write-Host "REACHOPS_LIVE_READINESS_DIR=$root"
Write-Host "LIVE_READINESS_JSON=$payloadPath"
if (-not [bool]$payload.ready) {
    throw "ReachOps live readiness blocked. See $payloadPath"
}
