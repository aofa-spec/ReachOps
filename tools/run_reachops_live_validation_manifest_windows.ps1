param(
    [string]$ProfileGroup = "BR",
    [string]$ProfileIds = "",
    [int]$ProfileLimit = 3,
    [int]$ProfileScanTimeout = 8,
    [int]$Limit = 3,
    [string]$AllowPressureSubmit = "",
    [string]$Target = "anti aging serum",
    [string]$CommentVideoUrl = "",
    [string]$TargetProfileUrl = "",
    [string]$DmProfileUrl = "",
    [string]$TargetUsername = "",
    [string]$ActivationStatusPath = "",
    [switch]$ConfirmAuthorizedTargets,
    [switch]$IncludeLiveSubmitCommand
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

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$root = "reports\reachops_live_validation\$stamp"
New-Item -ItemType Directory -Path $root -Force | Out-Null
$stdoutPath = Join-Path $root "live_validation_manifest_stdout.json"
$payloadPath = Join-Path $root "live_validation_manifest.json"

Write-Host "[ReachOpsValidation] Building real-platform validation manifest only." -ForegroundColor Cyan
Write-Host "[ReachOpsValidation] No browser will be opened. No comment/follow/dm will be submitted." -ForegroundColor Yellow

$argsList = @(
    "tools\reachops_live_validation_manifest.py",
    "--profile-group", $ProfileGroup,
    "--profile-limit", ([string]$ProfileLimit),
    "--profile-scan-timeout", ([string]$ProfileScanTimeout),
    "--limit", ([string]$Limit),
    "--target", $Target,
    "--json"
)
if ($AllowPressureSubmit) {
    $argsList += @("--allow-pressure-submit", $AllowPressureSubmit)
}
if ($ProfileIds) {
    $argsList += @("--profile-ids", $ProfileIds)
}
if ($CommentVideoUrl) {
    $argsList += @("--comment-video-url", $CommentVideoUrl)
}
if ($TargetProfileUrl) {
    $argsList += @("--target-profile-url", $TargetProfileUrl)
}
if ($DmProfileUrl) {
    $argsList += @("--dm-profile-url", $DmProfileUrl)
}
if ($TargetUsername) {
    $argsList += @("--target-username", $TargetUsername)
}
if ($ActivationStatusPath) {
    $argsList += @("--activation-status-path", $ActivationStatusPath)
}
if ($ConfirmAuthorizedTargets) {
    $argsList += @("--confirm-authorized-targets", "YES")
}
if ($IncludeLiveSubmitCommand) {
    $argsList += @("--include-live-submit-command")
}

$output = & python @argsList 2>&1
$exitCode = $LASTEXITCODE
$output | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $stdoutPath -Content ($output -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $stdoutPath -OutputPath $payloadPath

$payload = Get-Content -Path $payloadPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
Write-Host "REACHOPS_LIVE_VALIDATION_DIR=$root"
Write-Host "LIVE_VALIDATION_MANIFEST_JSON=$payloadPath"

if ([string]$payload.status -eq "blocked") {
    Write-Host "[ReachOpsValidation] Manifest is blocked. Missing inputs:" -ForegroundColor Yellow
    @($payload.missing_inputs) | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
    exit 2
}

if ($exitCode -ne 0) {
    exit $exitCode
}
