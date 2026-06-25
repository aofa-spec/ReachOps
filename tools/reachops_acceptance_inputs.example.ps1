# ReachOps Windows live acceptance input template.
#
# Copy this file to a local, untracked path before filling real values.
# Do not commit real profile IDs, target URLs, activation files, or customer data.
#
# Default behavior is safe: it runs readiness and preflight only.
# Controlled live submit runs only when $RunControlledLiveSubmit is set to $true.

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

# Required operator inputs.
$ProfileGroup = "BR"
$ProfileIds = "123,456,789"
$Target = "anti aging serum"
$CommentVideoUrl = "https://www.tiktok.com/@creator/video/123"
$FollowProfileUrl = "https://www.tiktok.com/@target_user"
$DmProfileUrl = "https://www.tiktok.com/@target_user"
$TargetUsername = "target_user"
$ActivationStatusPath = "C:\path\to\reachops_activation_status.json"

# Optional safety controls.
$Limit = 3
$AllowPressureSubmit = ""
$RunControlledLiveSubmit = $false

function Require-Value {
    param(
        [string]$Name,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is required."
    }
    if ($Value -match "123,456|creator/video/123|target_user|C:\\path\\to") {
        throw "$Name still contains a placeholder value: $Value"
    }
}

Require-Value "ProfileIds" $ProfileIds
Require-Value "CommentVideoUrl" $CommentVideoUrl
Require-Value "FollowProfileUrl" $FollowProfileUrl
Require-Value "DmProfileUrl" $DmProfileUrl
Require-Value "TargetUsername" $TargetUsername
Require-Value "ActivationStatusPath" $ActivationStatusPath

if (-not (Test-Path $ActivationStatusPath)) {
    throw "ActivationStatusPath does not exist: $ActivationStatusPath"
}

Write-Host "[ReachOpsInputs] Summarizing live acceptance state. No browser opens and no platform action submits." -ForegroundColor Cyan
python tools\reachops_live_acceptance_status.py `
    --profile-group $ProfileGroup `
    --profile-ids $ProfileIds `
    --comment-video-url $CommentVideoUrl `
    --target-profile-url $FollowProfileUrl `
    --dm-profile-url $DmProfileUrl `
    --target-username $TargetUsername `
    --activation-status-path $ActivationStatusPath `
    --confirm-authorized-targets `
    --json
if ($LASTEXITCODE -ne 0) {
    throw "Live acceptance status probe failed."
}

Write-Host "[ReachOpsInputs] Checking activation status. No browser opens and no platform action submits." -ForegroundColor Cyan
python tools\reachops_activation_status_check.py --activation-status-path $ActivationStatusPath --json
if ($LASTEXITCODE -ne 0) {
    throw "Activation status check blocked. Fix activation before readiness/preflight."
}

Write-Host "[ReachOpsInputs] Running readiness. No browser opens and no platform action submits." -ForegroundColor Cyan
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_readiness_windows.ps1 `
    -ProfileGroup $ProfileGroup `
    -ProfileIds $ProfileIds `
    -CommentVideoUrl $CommentVideoUrl `
    -TargetProfileUrl $FollowProfileUrl `
    -TargetUsername $TargetUsername `
    -ActivationStatusPath $ActivationStatusPath `
    -Limit $Limit `
    -AllowPressureSubmit $AllowPressureSubmit `
    -ConfirmAuthorizedTargets

Write-Host "[ReachOpsInputs] Running no-submit preflight." -ForegroundColor Cyan
powershell -ExecutionPolicy Bypass -File tools\run_reachops_live_preflight_windows.ps1 `
    -ProfileGroup $ProfileGroup `
    -ProfileIds $ProfileIds `
    -CommentVideoUrl $CommentVideoUrl `
    -TargetProfileUrl $FollowProfileUrl `
    -DmProfileUrl $DmProfileUrl `
    -TargetUsername $TargetUsername

if (-not $RunControlledLiveSubmit) {
    Write-Host "[ReachOpsInputs] Controlled live submit skipped. Set `$RunControlledLiveSubmit = `$true only after readiness/preflight evidence is approved." -ForegroundColor Yellow
    return
}

Write-Host "[ReachOpsInputs] Running controlled live submit. Confirm targets are authorized." -ForegroundColor Red
powershell -ExecutionPolicy Bypass -File tools\run_reachops_acceptance_windows.ps1 `
    -ProfileGroup $ProfileGroup `
    -ProfileIds $ProfileIds `
    -Target $Target `
    -CommentVideoUrl $CommentVideoUrl `
    -FollowProfileUrl $FollowProfileUrl `
    -DmProfileUrl $DmProfileUrl `
    -TargetUsername $TargetUsername `
    -ActivationStatusPath $ActivationStatusPath `
    -Limit $Limit `
    -AllowPressureSubmit $AllowPressureSubmit `
    -RunLiveSubmit `
    -ConfirmAuthorizedTargets
