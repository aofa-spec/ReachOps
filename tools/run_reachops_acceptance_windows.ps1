param(
    [string]$ProfileGroup = "BR",
    [string]$ProfileIds = "",
    [string]$Target = "anti aging serum",
    [string]$CommentVideoUrl = "",
    [string]$FollowProfileUrl = "",
    [string]$DmProfileUrl = "",
    [string]$TargetUsername = "",
    [string]$ActivationStatusPath = "",
    [int]$Limit = 3,
    [string]$AllowPressureSubmit = "",
    [switch]$AllowMissingInstaller,
    [switch]$RunLiveSubmit,
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

function Write-Step {
    param([string]$Message)
    Write-Host "[ReachOpsAcceptance] $Message" -ForegroundColor Cyan
}

function Assert-LastExitCode {
    param([string]$StepName)
    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE"
    }
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )
    if ([System.IO.Path]::IsPathRooted($Path)) {
        $outputFullPath = [System.IO.Path]::GetFullPath($Path)
    } else {
        $outputFullPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    }
    $outputDir = [System.IO.Path]::GetDirectoryName($outputFullPath)
    if ($outputDir -and -not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($outputFullPath, $Content, $utf8NoBom)
}

function Invoke-PythonCapture {
    param(
        [string]$StepName,
        [string]$StdoutPath,
        [string[]]$Arguments
    )
    $output = & python @Arguments 2>&1
    $output | ForEach-Object { Write-Host $_ }
    Assert-LastExitCode $StepName
    Write-Utf8NoBom -Path $StdoutPath -Content ($output -join [Environment]::NewLine)
}

function Invoke-PowerShellCapture {
    param(
        [string]$StepName,
        [string]$StdoutPath,
        [string[]]$Arguments
    )
    $output = & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass @Arguments 2>&1
    $output | ForEach-Object { Write-Host $_ }
    Assert-LastExitCode $StepName
    Write-Utf8NoBom -Path $StdoutPath -Content ($output -join [Environment]::NewLine)
}

function Convert-StdoutJson {
    param(
        [string]$StdoutPath,
        [string]$OutputPath
    )
    if (-not (Test-Path $StdoutPath)) {
        return ""
    }
    $raw = Get-Content -Path $StdoutPath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return ""
    }
    $idx = $raw.LastIndexOf("{")
    while ($idx -ge 0) {
        $candidate = $raw.Substring($idx).Trim()
        try {
            $null = $candidate | ConvertFrom-Json -ErrorAction Stop
            Write-Utf8NoBom -Path $OutputPath -Content $candidate
            return $OutputPath
        } catch {
            if ($idx -eq 0) {
                break
            }
            $idx = $raw.LastIndexOf("{", $idx - 1)
        }
    }
    throw "No valid JSON payload found in $StdoutPath"
}

function Read-JsonObject {
    param([string]$Path)
    if (!(Test-Path $Path)) {
        return $null
    }
    return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
}

function Empty-JsonArray {
    return ,[System.Collections.ArrayList]::new()
}

function Write-AcceptanceSummary {
    param(
        [string]$OutputPath,
        [string]$RootDir,
        [string]$AuditJsonPath,
        [string]$OperatorPressureJsonPath,
        [string]$InstallerSmokeJsonPath,
        [string]$UiStartupJsonPath,
        [string]$LiveValidationJsonPath,
        [string]$ReadinessJsonPath,
        [string]$PreflightJsonPath,
        [string]$LiveSubmitJsonPath,
        [bool]$InstallerOptional = $false
    )
    $audit = Read-JsonObject $AuditJsonPath
    $operatorPressure = Read-JsonObject $OperatorPressureJsonPath
    $installer = Read-JsonObject $InstallerSmokeJsonPath
    $uiStartup = Read-JsonObject $UiStartupJsonPath
    $liveValidation = Read-JsonObject $LiveValidationJsonPath
    $readiness = Read-JsonObject $ReadinessJsonPath
    $preflight = Read-JsonObject $PreflightJsonPath
    $liveSubmit = Read-JsonObject $LiveSubmitJsonPath

    $auditSummary = $audit.summary
    $auditFailed = 0
    $auditPending = 0
    if ($auditSummary) {
        $auditFailed = [int]($auditSummary.failed)
        $auditPending = [int]($auditSummary.pending_external_validation)
    }

    $operatorPressureOk = $false
    if ($operatorPressure) {
        $operatorPressureSummary = $operatorPressure.summary
        $operatorPressureOk = (
            ([string]$operatorPressure.status -eq "ok") -and
            ([int]$operatorPressure.campaign_count -ge 3) -and
            ([int]$operatorPressureSummary.content_found -gt 0) -and
            ([int]$operatorPressureSummary.comment_users -gt 0) -and
            ([int]$operatorPressureSummary.customer_leads -gt 0) -and
            ([int]$operatorPressureSummary.outreach_actions -gt 0) -and
            ([int]$operatorPressureSummary.execution_success -gt 0) -and
            ([int]$operatorPressureSummary.account_switched -gt 0)
        )
    }

    $installerOk = $false
    if ($installer) {
        $installerOk = ([string]$installer.status -eq "ok") -and [bool]$installer.exe_exists -and (-not [bool]$installer.data_in_install_dir) -and [bool]$installer.hash_ok
    } elseif ($InstallerOptional) {
        $installerOk = $true
    }

    $uiStartupOk = $false
    if ($uiStartup) {
        $uiStartupOk = ([string]$uiStartup.status -eq "ok") -and [bool]$uiStartup.process_running -and [bool]$uiStartup.interactive_task
    }

    $preflightStatus = "skipped"
    if ($preflight) {
        $preflightStatus = "completed"
    }

    $liveSubmitStatus = "skipped"
    $liveSubmitPlatformValidation = $false
    $liveSubmitActivationLoaded = $false
    if ($liveSubmit) {
        if ([bool]$liveSubmit.passed) {
            $liveSubmitStatus = "completed"
            $liveSubmitPlatformValidation = [bool]$liveSubmit.platform_validation
            $liveSubmitActivationLoaded = [bool]$liveSubmit.activation_status_loaded
        } else {
            $liveSubmitStatus = "failed"
        }
    }
    $resolvedExternalValidation = 0
    if ($liveSubmitStatus -eq "completed" -and $liveSubmitPlatformValidation -and $auditPending -gt 0) {
        $resolvedExternalValidation = 1
    }
    $effectivePending = [Math]::Max(0, $auditPending - $resolvedExternalValidation)

    $status = "ready_for_external_validation"
    if ($auditFailed -gt 0 -or -not $operatorPressureOk -or -not $installerOk -or -not $uiStartupOk -or $liveSubmitStatus -eq "failed") {
        $status = "failed"
    } elseif ($effectivePending -eq 0 -and $liveSubmitStatus -eq "completed") {
        $status = "passed"
    }

    $summary = [ordered]@{
        status = $status
        acceptance_dir = $RootDir
        delivery_audit = [ordered]@{
            status = [string]$audit.status
            passed = [int]$auditSummary.passed
            pending_external_validation = $auditPending
            resolved_external_validation = $resolvedExternalValidation
            effective_pending_external_validation = $effectivePending
            failed = $auditFailed
            processed_sources = [int]$auditSummary.processed_sources
            action_selected = [int]$auditSummary.action_selected
            json_path = $AuditJsonPath
        }
        operator_pressure = [ordered]@{
            status = if ($operatorPressure) { [string]$operatorPressure.status } else { "skipped" }
            campaign_count = if ($operatorPressure) { [int]$operatorPressure.campaign_count } else { 0 }
            target_sources = if ($operatorPressure) { [int]$operatorPressure.summary.target_sources } else { 0 }
            content_found = if ($operatorPressure) { [int]$operatorPressure.summary.content_found } else { 0 }
            comment_users = if ($operatorPressure) { [int]$operatorPressure.summary.comment_users } else { 0 }
            customer_leads = if ($operatorPressure) { [int]$operatorPressure.summary.customer_leads } else { 0 }
            outreach_actions = if ($operatorPressure) { [int]$operatorPressure.summary.outreach_actions } else { 0 }
            selected_actions = if ($operatorPressure) { [int]$operatorPressure.summary.selected_actions } else { 0 }
            execution_success = if ($operatorPressure) { [int]$operatorPressure.summary.execution_success } else { 0 }
            execution_failed = if ($operatorPressure) { [int]$operatorPressure.summary.execution_failed } else { 0 }
            account_switched = if ($operatorPressure) { [int]$operatorPressure.summary.account_switched } else { 0 }
            workers = if ($operatorPressure) { [int]$operatorPressure.summary.workers } else { 0 }
            json_path = if (Test-Path $OperatorPressureJsonPath) { $OperatorPressureJsonPath } else { "" }
        }
        installer_smoke = [ordered]@{
            status = if ($installer) { [string]$installer.status } elseif ($InstallerOptional) { "skipped_optional" } else { "skipped" }
            optional = [bool]$InstallerOptional
            exe_exists = if ($installer) { [bool]$installer.exe_exists } else { $false }
            data_in_install_dir = if ($installer) { [bool]$installer.data_in_install_dir } else { $false }
            hash_ok = if ($installer) { [bool]$installer.hash_ok } else { $false }
            manifest_version = if ($installer) { [string]$installer.manifest_version } else { "" }
            manifest_build = if ($installer) { [string]$installer.manifest_build } else { "" }
            json_path = if (Test-Path $InstallerSmokeJsonPath) { $InstallerSmokeJsonPath } else { "" }
        }
        ui_startup = [ordered]@{
            status = if ($uiStartup) { [string]$uiStartup.status } else { "skipped" }
            process_running = if ($uiStartup) { [bool]$uiStartup.process_running } else { $false }
            interactive_task = if ($uiStartup) { [bool]$uiStartup.interactive_task } else { $false }
            pid = if ($uiStartup) { [int]$uiStartup.pid } else { 0 }
            json_path = if (Test-Path $UiStartupJsonPath) { $UiStartupJsonPath } else { "" }
        }
        live_preflight = [ordered]@{
            status = $preflightStatus
            preflight_action_statuses = if ($preflight) { $preflight.preflight_action_statuses } else { @{} }
            missing_preflight_action_types = if ($preflight) { @($preflight.missing_preflight_action_types) } else { Empty-JsonArray }
            json_path = if (Test-Path $PreflightJsonPath) { $PreflightJsonPath } else { "" }
        }
        live_validation = [ordered]@{
            status = if ($liveValidation) { [string]$liveValidation.status } else { "skipped" }
            no_browser_started = if ($liveValidation) { [bool]$liveValidation.no_browser_started } else { $true }
            no_submit = if ($liveValidation) { [bool]$liveValidation.no_submit } else { $true }
            selected_profile_ids = if ($liveValidation) { @($liveValidation.selected_profile_ids) } else { Empty-JsonArray }
            missing_inputs = if ($liveValidation) { @($liveValidation.missing_inputs) } else { Empty-JsonArray }
            activation_status_path = if ($liveValidation) { [string]$liveValidation.activation_status_path } else { "" }
            json_path = if (Test-Path $LiveValidationJsonPath) { $LiveValidationJsonPath } else { "" }
        }
        live_readiness = [ordered]@{
            status = if ($readiness) { [string]$readiness.status } else { "skipped" }
            ready = if ($readiness) { [bool]$readiness.ready } else { $false }
            no_browser_started = if ($readiness) { [bool]$readiness.no_browser_started } else { $true }
            no_submit = if ($readiness) { [bool]$readiness.no_submit } else { $true }
            activation_status_path = if ($readiness) { [string]$readiness.activation_status_path } else { "" }
            checks = if ($readiness) { @($readiness.checks) } else { Empty-JsonArray }
            json_path = if (Test-Path $ReadinessJsonPath) { $ReadinessJsonPath } else { "" }
        }
        live_submit = [ordered]@{
            status = $liveSubmitStatus
            executor_mode = if ($liveSubmit) { [string]$liveSubmit.executor_mode } else { "" }
            platform_validation = $liveSubmitPlatformValidation
            activation_status_loaded = $liveSubmitActivationLoaded
            activation_status_source = if ($liveSubmit) { [string]$liveSubmit.activation_status_source } else { "" }
            activation_status_path = if ($liveSubmit) { [string]$liveSubmit.activation_status_path } else { "" }
            evidence_by_action_type = if ($liveSubmit) { $liveSubmit.evidence_by_action_type } else { @{} }
            evidence_file_details = if ($liveSubmit) { $liveSubmit.evidence_file_details } else { @{} }
            missing_evidence_action_types = if ($liveSubmit) { @($liveSubmit.missing_evidence_action_types) } else { Empty-JsonArray }
            missing_local_evidence_file_action_types = if ($liveSubmit) { @($liveSubmit.missing_local_evidence_file_action_types) } else { Empty-JsonArray }
            json_path = if (Test-Path $LiveSubmitJsonPath) { $LiveSubmitJsonPath } else { "" }
        }
    }
    Write-Utf8NoBom -Path $OutputPath -Content ($summary | ConvertTo-Json -Depth 8 -Compress)
}

function Add-GoalStatusToAcceptanceSummary {
    param(
        [string]$SummaryPath,
        [string]$GoalStatusJsonPath
    )
    if (!(Test-Path $SummaryPath) -or !(Test-Path $GoalStatusJsonPath)) {
        return
    }
    $summary = Read-JsonObject $SummaryPath
    $goalStatus = Read-JsonObject $GoalStatusJsonPath
    if (!$summary -or !$goalStatus) {
        return
    }
    $goalStatus | Add-Member -NotePropertyName "json_path" -NotePropertyValue $GoalStatusJsonPath -Force
    $summary | Add-Member -NotePropertyName "goal_status" -NotePropertyValue $goalStatus -Force
    Write-Utf8NoBom -Path $SummaryPath -Content ($summary | ConvertTo-Json -Depth 12 -Compress)
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$root = "reports\reachops_acceptance\$stamp"
New-Item -ItemType Directory -Path $root -Force | Out-Null

$auditStdout = Join-Path $root "delivery_audit_stdout.json"
$auditJson = Join-Path $root "delivery_audit_payload.json"
$operatorPressureStdout = Join-Path $root "operator_pressure_stdout.json"
$operatorPressureJson = Join-Path $root "operator_pressure_payload.json"
$preflightStdout = Join-Path $root "live_preflight_stdout.json"
$preflightJson = Join-Path $root "live_preflight_payload.json"
$readinessStdout = Join-Path $root "live_readiness_stdout.json"
$readinessJson = Join-Path $root "live_readiness_payload.json"
$liveSubmitStdout = Join-Path $root "live_submit_stdout.json"
$liveSubmitJson = Join-Path $root "live_submit_payload.json"
$installerSmokeStdout = Join-Path $root "installer_smoke_stdout.json"
$installerSmokeJson = Join-Path $root "installer_smoke_payload.json"
$uiStartupStdout = Join-Path $root "ui_startup_stdout.json"
$uiStartupJson = Join-Path $root "ui_startup_payload.json"
$liveValidationStdout = Join-Path $root "live_validation_manifest_stdout.json"
$liveValidationJson = Join-Path $root "live_validation_manifest.json"
$goalStatusStdout = Join-Path $root "goal_status_stdout.json"
$goalStatusJson = Join-Path $root "goal_status_report.json"
$packageCheckStdout = Join-Path $root "delivery_package_check_stdout.json"
$packageCheckJson = Join-Path $root "delivery_package_check.json"
$acceptanceSummaryJson = Join-Path $root "acceptance_summary.json"

Write-Step "ReachOps delivery audit"
Invoke-PythonCapture -StepName "ReachOps delivery audit" -StdoutPath $auditStdout -Arguments @("tools\reachops_delivery_audit.py", "--target", $Target, "--json")
Convert-StdoutJson -StdoutPath $auditStdout -OutputPath $auditJson | Out-Null

Write-Step "ReachOps operator pressure"
Invoke-PythonCapture -StepName "ReachOps operator pressure" -StdoutPath $operatorPressureStdout -Arguments @("tools\reachops_operator_pressure.py", "--profile-group", $ProfileGroup, "--targets", "$Target,https://www.tiktok.com/@beauty_creator,#makeupfinds", "--json")
Convert-StdoutJson -StdoutPath $operatorPressureStdout -OutputPath $operatorPressureJson | Out-Null

$installerSmokeScript = "tools\run_reachops_installer_smoke_windows.ps1"
$installerPath = "dist\installer\ReachOps-Setup-0.4.0.exe"
if ((Test-Path $installerSmokeScript) -and (Test-Path $installerPath)) {
    Write-Step "ReachOps installer smoke"
    Invoke-PowerShellCapture -StepName "ReachOps installer smoke" -StdoutPath $installerSmokeStdout -Arguments @("-File", $installerSmokeScript, "-Root", (Get-Location).ProviderPath, "-ReportPath", (Join-Path $root "installer_smoke_report.json"))
    Convert-StdoutJson -StdoutPath $installerSmokeStdout -OutputPath $installerSmokeJson | Out-Null
} else {
    Write-Step "Skipping installer smoke: installer or smoke script not found"
}

$uiStartupSmokeScript = "tools\run_reachops_ui_startup_smoke_windows.ps1"
if (Test-Path $uiStartupSmokeScript) {
    Write-Step "ReachOps UI startup smoke"
    Invoke-PowerShellCapture -StepName "ReachOps UI startup smoke" -StdoutPath $uiStartupStdout -Arguments @("-File", $uiStartupSmokeScript, "-Root", (Get-Location).ProviderPath, "-KeepRunning")
    Convert-StdoutJson -StdoutPath $uiStartupStdout -OutputPath $uiStartupJson | Out-Null
} else {
    Write-Step "Skipping UI startup smoke: script not found"
}

Write-Step "ReachOps live validation manifest without browser"
$liveValidationArgs = @("tools\reachops_live_validation_manifest.py", "--profile-group", $ProfileGroup, "--profile-limit", "3", "--profile-scan-timeout", "5", "--limit", ([string]$Limit), "--target", $Target, "--json")
if ($AllowPressureSubmit) {
    $liveValidationArgs += @("--allow-pressure-submit", $AllowPressureSubmit)
}
if ($ProfileIds) {
    $liveValidationArgs += @("--profile-ids", $ProfileIds)
}
if ($CommentVideoUrl) {
    $liveValidationArgs += @("--comment-video-url", $CommentVideoUrl)
}
if ($FollowProfileUrl) {
    $liveValidationArgs += @("--target-profile-url", $FollowProfileUrl)
}
if ($DmProfileUrl) {
    $liveValidationArgs += @("--dm-profile-url", $DmProfileUrl)
}
if ($TargetUsername) {
    $liveValidationArgs += @("--target-username", $TargetUsername)
}
if ($ActivationStatusPath) {
    $liveValidationArgs += @("--activation-status-path", $ActivationStatusPath)
}
if ($ConfirmAuthorizedTargets) {
    $liveValidationArgs += @("--confirm-authorized-targets", "YES")
}
$liveValidationOutput = & python @liveValidationArgs 2>&1
$liveValidationOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $liveValidationStdout -Content ($liveValidationOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $liveValidationStdout -OutputPath $liveValidationJson | Out-Null

if ($ProfileIds -and $CommentVideoUrl -and $FollowProfileUrl -and $TargetUsername) {
    Write-Step "ReachOps live submit readiness check without browser"
    $readinessArgs = @("tools\reachops_live_readiness.py", "--profile-ids", $ProfileIds, "--group-name", $ProfileGroup, "--video-url", $CommentVideoUrl, "--follow-profile-url", $FollowProfileUrl, "--dm-profile-url", $(if ($DmProfileUrl) { $DmProfileUrl } else { $FollowProfileUrl }), "--target-username", $TargetUsername, "--limit", ([string]$Limit), "--json")
    if ($AllowPressureSubmit) {
        $readinessArgs += @("--allow-pressure-submit", $AllowPressureSubmit)
    }
    if ($ConfirmAuthorizedTargets) {
        $readinessArgs += @("--confirm-authorized-targets", "YES")
    }
    if ($ActivationStatusPath) {
        $readinessArgs += @("--activation-status-path", $ActivationStatusPath)
    }
    $readinessOutput = & python @readinessArgs 2>&1
    $readinessOutput | ForEach-Object { Write-Host $_ }
    Write-Utf8NoBom -Path $readinessStdout -Content ($readinessOutput -join [Environment]::NewLine)
    Convert-StdoutJson -StdoutPath $readinessStdout -OutputPath $readinessJson | Out-Null
    $readinessPayload = Read-JsonObject $readinessJson

    if ($readinessPayload -and [bool]$readinessPayload.ready) {
        Write-Step "ReachOps live preflight without submit"
        Invoke-PythonCapture -StepName "ReachOps live preflight" -StdoutPath $preflightStdout -Arguments @("tools\reachops_live_preflight.py", "--base-dir", (Join-Path $root "live_preflight"), "--profile-ids", $ProfileIds, "--group-name", $ProfileGroup, "--video-url", $CommentVideoUrl, "--profile-url", $FollowProfileUrl, "--target-username", $TargetUsername, "--workers", "2", "--per-profile-limit", "3", "--switch-attempts", "2", "--page-timeout", "45", "--element-timeout", "25", "--json")
        Convert-StdoutJson -StdoutPath $preflightStdout -OutputPath $preflightJson | Out-Null
    } else {
        Write-Step "Skipping live preflight: live readiness is blocked"
    }
} else {
    Write-Step "Skipping live readiness/preflight: ProfileIds, CommentVideoUrl, FollowProfileUrl, or TargetUsername not provided"
}

if ($RunLiveSubmit) {
    if (-not $ConfirmAuthorizedTargets) {
        throw "RunLiveSubmit requires -ConfirmAuthorizedTargets."
    }
    if (-not ($ProfileIds -and $CommentVideoUrl -and $FollowProfileUrl -and $DmProfileUrl -and $TargetUsername)) {
        throw "RunLiveSubmit requires ProfileIds, CommentVideoUrl, FollowProfileUrl, DmProfileUrl, and TargetUsername."
    }
    if (-not (Test-Path $readinessJson)) {
        throw "RunLiveSubmit requires live readiness check."
    }
    $readinessPayload = Read-JsonObject $readinessJson
    if (-not ($readinessPayload -and [bool]$readinessPayload.ready)) {
        throw "RunLiveSubmit requires live readiness status ready."
    }
    Write-Step "ReachOps controlled live submit: comment + follow + DM"
    $liveSubmitArgs = @("tools\reachops_live_submit_acceptance.py", "--base-dir", (Join-Path $root "live_submit"), "--profile-ids", $ProfileIds, "--group-name", $ProfileGroup, "--video-url", $CommentVideoUrl, "--follow-profile-url", $FollowProfileUrl, "--dm-profile-url", $DmProfileUrl, "--target-username", $TargetUsername, "--confirm-authorized-targets", "YES", "--workers", "1", "--per-profile-limit", "3", "--limit", ([string]$Limit), "--page-timeout", "45", "--element-timeout", "25", "--json")
    if ($AllowPressureSubmit) {
        $liveSubmitArgs += @("--allow-pressure-submit", $AllowPressureSubmit)
    }
    if ($ActivationStatusPath) {
        $liveSubmitArgs += @("--activation-status-path", $ActivationStatusPath)
    }
    Invoke-PythonCapture -StepName "ReachOps controlled live submit" -StdoutPath $liveSubmitStdout -Arguments $liveSubmitArgs
    Convert-StdoutJson -StdoutPath $liveSubmitStdout -OutputPath $liveSubmitJson | Out-Null
} else {
    Write-Step "Skipping controlled live submit: RunLiveSubmit not set"
}

Write-AcceptanceSummary -OutputPath $acceptanceSummaryJson -RootDir $root -AuditJsonPath $auditJson -OperatorPressureJsonPath $operatorPressureJson -InstallerSmokeJsonPath $installerSmokeJson -UiStartupJsonPath $uiStartupJson -LiveValidationJsonPath $liveValidationJson -ReadinessJsonPath $readinessJson -PreflightJsonPath $preflightJson -LiveSubmitJsonPath $liveSubmitJson -InstallerOptional ([bool]$AllowMissingInstaller)

Write-Step "ReachOps goal status report"
Invoke-PythonCapture -StepName "ReachOps goal status report" -StdoutPath $goalStatusStdout -Arguments @("tools\reachops_goal_status_report.py", "--audit-json", $auditJson, "--acceptance-summary", $acceptanceSummaryJson, "--json")
Convert-StdoutJson -StdoutPath $goalStatusStdout -OutputPath $goalStatusJson | Out-Null
Add-GoalStatusToAcceptanceSummary -SummaryPath $acceptanceSummaryJson -GoalStatusJsonPath $goalStatusJson

Write-Step "ReachOps delivery package check"
$packageCheckArgs = @("tools\reachops_delivery_package_check.py", "--acceptance-summary", $acceptanceSummaryJson, "--json")
$currentSummary = Read-JsonObject $acceptanceSummaryJson
if (-not ($currentSummary -and [string]$currentSummary.status -eq "passed")) {
    $packageCheckArgs += @("--allow-external-pending")
}
$packageCheckOutput = & python @packageCheckArgs 2>&1
$packageCheckOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $packageCheckStdout -Content ($packageCheckOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $packageCheckStdout -OutputPath $packageCheckJson | Out-Null
$packageCheckPayload = Read-JsonObject $packageCheckJson
if ($currentSummary -and [string]$currentSummary.status -eq "passed" -and (-not ($packageCheckPayload -and [bool]$packageCheckPayload.passed))) {
    throw "ReachOps delivery package check failed for final passed acceptance. See $packageCheckJson"
}

Write-Step "ReachOps acceptance artifacts written under $root"
Write-Host "REACHOPS_ACCEPTANCE_DIR=$root"
Write-Host "DELIVERY_AUDIT_JSON=$auditJson"
Write-Host "OPERATOR_PRESSURE_JSON=$operatorPressureJson"
Write-Host "LIVE_VALIDATION_MANIFEST_JSON=$liveValidationJson"
Write-Host "GOAL_STATUS_JSON=$goalStatusJson"
Write-Host "PACKAGE_CHECK_JSON=$packageCheckJson"
Write-Host "ACCEPTANCE_SUMMARY_JSON=$acceptanceSummaryJson"
if (Test-Path $preflightJson) {
    Write-Host "LIVE_PREFLIGHT_JSON=$preflightJson"
}
if (Test-Path $readinessJson) {
    Write-Host "LIVE_READINESS_JSON=$readinessJson"
}
if (Test-Path $liveSubmitJson) {
    Write-Host "LIVE_SUBMIT_JSON=$liveSubmitJson"
}
if (Test-Path $installerSmokeJson) {
    Write-Host "INSTALLER_SMOKE_JSON=$installerSmokeJson"
}
if (Test-Path $uiStartupJson) {
    Write-Host "UI_STARTUP_JSON=$uiStartupJson"
}
