param(
    [string]$OutputPath = "tools\reachops_acceptance_inputs.local.ps1",
    [string]$ProfileGroup = "",
    [string]$ProfileIds = "",
    [string]$Target = "",
    [string]$CommentVideoUrl = "",
    [string]$FollowProfileUrl = "",
    [string]$DmProfileUrl = "",
    [string]$TargetUsername = "",
    [string]$ActivationStatusPath = "",
    [switch]$ConfirmAuthorizedTargets,
    [switch]$UpdateExisting,
    [switch]$Force,
    [switch]$Json
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
    if ([System.IO.Path]::IsPathRooted($Path)) {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
    } else {
        $fullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    }
    $dir = [System.IO.Path]::GetDirectoryName($fullPath)
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($fullPath, $Content, $utf8NoBom)
}

function Set-InputValue {
    param(
        [string]$Content,
        [string]$Name,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Content
    }
    $escaped = $Value.Replace("`", "``").Replace('"', '`"')
    $replacement = '$$' + $Name + ' = "' + $escaped + '"'
    return [regex]::Replace(
        $Content,
        "(?m)^\s*\$$([regex]::Escape($Name))\s*=.*$",
        $replacement
    )
}

$templatePath = Join-Path $RepoRoot "tools\reachops_acceptance_inputs.example.ps1"
if (!(Test-Path $templatePath)) {
    throw "Template missing: $templatePath"
}

if ((Test-Path $OutputPath) -and -not ($Force -or $UpdateExisting)) {
    throw "$OutputPath already exists. Review it directly, rerun with -UpdateExisting to set only supplied fields, or rerun with -Force only after backing up real authorized targets."
}

if ((Test-Path $OutputPath) -and $UpdateExisting) {
    $content = Get-Content -Path $OutputPath -Raw -Encoding UTF8
} else {
    $content = Get-Content -Path $templatePath -Raw -Encoding UTF8
}
$content = Set-InputValue $content "ProfileGroup" $ProfileGroup
$content = Set-InputValue $content "ProfileIds" $ProfileIds
$content = Set-InputValue $content "Target" $Target
$content = Set-InputValue $content "CommentVideoUrl" $CommentVideoUrl
$content = Set-InputValue $content "FollowProfileUrl" $FollowProfileUrl
$content = Set-InputValue $content "DmProfileUrl" $DmProfileUrl
$content = Set-InputValue $content "TargetUsername" $TargetUsername
$content = Set-InputValue $content "ActivationStatusPath" $ActivationStatusPath
if ($ConfirmAuthorizedTargets) {
    $content = [regex]::Replace(
        $content,
        "(?m)^\s*\$ConfirmAuthorizedTargets\s*=.*$",
        '$ConfirmAuthorizedTargets = $true'
    )
}

Write-Utf8NoBom -Path $OutputPath -Content $content

if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $resolvedOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
} else {
    $resolvedOutputPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $OutputPath))
}

if ($Json) {
    $python = "python"
    $statusJson = & $python tools\reachops_live_acceptance_status.py --local-inputs-path $resolvedOutputPath --write-report --json-report-path --json
    if ($LASTEXITCODE -ne 0) {
        throw "reachops_live_acceptance_status.py failed with exit code $LASTEXITCODE"
    }
    $readiness = $statusJson | ConvertFrom-Json
    [ordered]@{
        status = $(if ($UpdateExisting) { "updated" } else { "created" })
        created = -not [bool]$UpdateExisting
        updated = [bool]$UpdateExisting
        path = $resolvedOutputPath
        no_browser_started = $true
        no_submit = $true
        local_inputs = $readiness.local_inputs
        readiness_status = $readiness.status
        final_delivery_ready = [bool]$readiness.final_delivery_ready
        report_path = $readiness.report_path
        json_report_path = $readiness.json_report_path
        next_required_actions = $readiness.next_required_actions
        operator_commands = $readiness.operator_commands
        verification_commands = @(
            "python tools\reachops_live_acceptance_status.py --write-report --json-report-path --json",
            "python tools\reachops_client_delivery_check.py --json",
            "python tools\reachops_delivery_package_check.py --json",
            "python tools\reachops_final_acceptance_gate.py --json"
        )
    } | ConvertTo-Json -Depth 12
    exit 0
}

Write-Host "[ReachOpsInputs] Wrote $OutputPath" -ForegroundColor Cyan
Write-Host "[ReachOpsInputs] The file is git-ignored. Fill only authorized TikTok targets and a real activation status path." -ForegroundColor Yellow
Write-Host "[ReachOpsInputs] Validate without opening a browser or submitting actions:" -ForegroundColor Cyan
Write-Host "python tools\reachops_live_acceptance_status.py --write-report --json"
