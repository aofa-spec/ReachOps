param(
    [string]$InputFile = "",
    [string]$ProfileGroup = "United States",
    [string]$ProfileIds = "",
    [string]$Target = "anti aging serum",
    [string]$CommentVideoUrl = "",
    [string]$FollowProfileUrl = "",
    [string]$DmProfileUrl = "",
    [string]$TargetUsername = "",
    [string]$ActivationStatusPath = "",
    [string]$LicenseEndpoint = "",
    [int]$Limit = 3,
    [string]$AllowPressureSubmit = "",
    [switch]$AllowMissingInstaller,
    [switch]$ReuseExistingUiStartup,
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

function Convert-AcceptanceInputLiteral {
    param([string]$Value)
    $text = ([string]$Value).Trim()
    if ($text -match '^\$true$') {
        return $true
    }
    if ($text -match '^\$false$') {
        return $false
    }
    if ($text -match '^-?\d+$') {
        return [int]$text
    }
    if ($text -match '^"(.*)"$') {
        return (($Matches[1] -replace '""', '"') -replace '`"', '"')
    }
    if ($text -match "^'(.*)'$") {
        return ($Matches[1] -replace "''", "'")
    }
    return $text
}

function Import-AcceptanceInputFile {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    $inputPath = if ([System.IO.Path]::IsPathRooted($Path)) {
        [System.IO.Path]::GetFullPath($Path)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
    }
    if (-not (Test-Path $inputPath)) {
        throw "InputFile does not exist: $inputPath"
    }
    foreach ($line in Get-Content -Path $inputPath -Encoding UTF8) {
        if ($line -match '^\s*\$(ProfileGroup|ProfileIds|Target|CommentVideoUrl|FollowProfileUrl|DmProfileUrl|TargetUsername|ActivationStatusPath|Limit|AllowPressureSubmit|ConfirmAuthorizedTargets|RunControlledLiveSubmit)\s*=\s*(.+?)\s*$') {
            $name = $Matches[1]
            $value = Convert-AcceptanceInputLiteral $Matches[2]
            switch ($name) {
                "ProfileGroup" { $script:ProfileGroup = [string]$value }
                "ProfileIds" { $script:ProfileIds = [string]$value }
                "Target" { $script:Target = [string]$value }
                "CommentVideoUrl" { $script:CommentVideoUrl = [string]$value }
                "FollowProfileUrl" { $script:FollowProfileUrl = [string]$value }
                "DmProfileUrl" { $script:DmProfileUrl = [string]$value }
                "TargetUsername" { $script:TargetUsername = [string]$value }
                "ActivationStatusPath" { $script:ActivationStatusPath = [string]$value }
                "Limit" { $script:Limit = [int]$value }
                "AllowPressureSubmit" { $script:AllowPressureSubmit = [string]$value }
                "ConfirmAuthorizedTargets" { $script:ConfirmAuthorizedTargets = [bool]$value }
                "RunControlledLiveSubmit" { $script:RunLiveSubmit = [bool]$value }
            }
        }
    }
    return $inputPath
}

function Empty-JsonArray {
    return ,[System.Collections.ArrayList]::new()
}

$ResolvedInputFile = Import-AcceptanceInputFile $InputFile

function Write-AcceptanceSummary {
    param(
        [string]$OutputPath,
        [string]$RootDir,
        [string]$AuditJsonPath,
        [string]$OperatorPressureJsonPath,
        [string]$InstallerSmokeJsonPath,
        [string]$UiStartupJsonPath,
        [string]$LicenseRefreshJsonPath,
        [string]$ActivationStatusJsonPath,
        [string]$LiveAcceptanceStatusJsonPath,
        [string]$AuthorizationHandoffJsonPath,
        [string]$LiveValidationJsonPath,
        [string]$RepositoryCleanlinessJsonPath,
        [string]$WindowsPackagePreflightJsonPath,
        [string]$ClientDeliveryJsonPath,
        [string]$ReadinessJsonPath,
        [string]$PreflightJsonPath,
        [string]$LiveSubmitJsonPath,
        [bool]$InstallerOptional = $false
    )
    $audit = Read-JsonObject $AuditJsonPath
    $operatorPressure = Read-JsonObject $OperatorPressureJsonPath
    $installer = Read-JsonObject $InstallerSmokeJsonPath
    $uiStartup = Read-JsonObject $UiStartupJsonPath
    $licenseRefresh = Read-JsonObject $LicenseRefreshJsonPath
    $activationStatus = Read-JsonObject $ActivationStatusJsonPath
    $liveAcceptanceStatus = Read-JsonObject $LiveAcceptanceStatusJsonPath
    $authorizationHandoff = Read-JsonObject $AuthorizationHandoffJsonPath
    $liveValidation = Read-JsonObject $LiveValidationJsonPath
    $windowsPackagePreflight = Read-JsonObject $WindowsPackagePreflightJsonPath
    $clientDelivery = Read-JsonObject $ClientDeliveryJsonPath
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

    $clientDeliveryOk = $false
    if ($clientDelivery) {
        $clientDeliveryOk = (
            ([string]$clientDelivery.status -eq "passed") -and
            ([string]$clientDelivery.readiness -eq "pass") -and
            [bool]$clientDelivery.contract_ok -and
            [bool]$clientDelivery.acceptance_ready -and
            [bool]$clientDelivery.final_delivery_ready -and
            (@($clientDelivery.failed_checks).Count -eq 0)
        )
    }

    $preflightStatus = "skipped"
    if ($preflight) {
        $preflightStatus = [string]$preflight.status
        if ([string]::IsNullOrWhiteSpace($preflightStatus)) {
            $preflightStatus = "completed"
        }
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
        $resolvedExternalValidation = $auditPending
    }
    $effectivePending = [Math]::Max(0, $auditPending - $resolvedExternalValidation)

    $status = "ready_for_external_validation"
    if ($auditFailed -gt 0 -or -not $operatorPressureOk -or -not $installerOk -or -not $uiStartupOk -or -not $clientDeliveryOk -or $liveSubmitStatus -eq "failed") {
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
        license_refresh = [ordered]@{
            status = if ($licenseRefresh) { [string]$licenseRefresh.status } else { "skipped" }
            refreshed = if ($licenseRefresh) { [bool]$licenseRefresh.refreshed } else { $false }
            endpoint_configured = if ($licenseRefresh) { [bool]$licenseRefresh.endpoint_configured } else { $false }
            activation_status_path = if ($licenseRefresh) { [string]$licenseRefresh.activation_status_path } else { "" }
            no_browser_started = if ($licenseRefresh) { [bool]$licenseRefresh.no_browser_started } else { $true }
            no_submit = if ($licenseRefresh) { [bool]$licenseRefresh.no_submit } else { $true }
            customer_data_uploaded = if ($licenseRefresh) { [bool]$licenseRefresh.customer_data_uploaded } else { $false }
            request_payload = if ($licenseRefresh) { $licenseRefresh.request_payload } else { @{} }
            json_path = if (Test-Path $LicenseRefreshJsonPath) { $LicenseRefreshJsonPath } else { "" }
        }
        activation_status = [ordered]@{
            status = if ($activationStatus) { [string]$activationStatus.status } else { "skipped" }
            ready = if ($activationStatus) { [bool]$activationStatus.ready } else { $false }
            no_browser_started = if ($activationStatus) { [bool]$activationStatus.no_browser_started } else { $true }
            no_submit = if ($activationStatus) { [bool]$activationStatus.no_submit } else { $true }
            activation_status_path = if ($activationStatus) { [string]$activationStatus.activation_status_path } else { "" }
            activation_status_exists = if ($activationStatus) { [bool]$activationStatus.activation_status_exists } else { $false }
            current_device_id = if ($activationStatus) { [string]$activationStatus.current_device_id } else { "" }
            checks = if ($activationStatus) { @($activationStatus.checks) } else { Empty-JsonArray }
            json_path = if (Test-Path $ActivationStatusJsonPath) { $ActivationStatusJsonPath } else { "" }
        }
        live_acceptance_status = [ordered]@{
            status = if ($liveAcceptanceStatus) { [string]$liveAcceptanceStatus.status } else { "skipped" }
            ready_for_live_preflight = if ($liveAcceptanceStatus) { [bool]$liveAcceptanceStatus.ready_for_live_preflight } else { $false }
            ready_for_live_submit = if ($liveAcceptanceStatus) { [bool]$liveAcceptanceStatus.ready_for_live_submit } else { $false }
            final_delivery_ready = if ($liveAcceptanceStatus) { [bool]$liveAcceptanceStatus.final_delivery_ready } else { $false }
            no_browser_started = if ($liveAcceptanceStatus) { [bool]$liveAcceptanceStatus.no_browser_started } else { $true }
            no_submit = if ($liveAcceptanceStatus) { [bool]$liveAcceptanceStatus.no_submit } else { $true }
            next_required_actions = if ($liveAcceptanceStatus) { @($liveAcceptanceStatus.next_required_actions) } else { Empty-JsonArray }
            verification_commands = if ($liveAcceptanceStatus) { @($liveAcceptanceStatus.verification_commands) } else { Empty-JsonArray }
            json_path = if (Test-Path $LiveAcceptanceStatusJsonPath) { $LiveAcceptanceStatusJsonPath } else { "" }
        }
        authorization_handoff = [ordered]@{
            status = if ($authorizationHandoff) { [string]$authorizationHandoff.status } else { "skipped" }
            exists = if ($authorizationHandoff) { [bool]$authorizationHandoff.exists } else { $false }
            final_delivery_ready = if ($authorizationHandoff) { [bool]$authorizationHandoff.final_delivery_ready } else { $false }
            no_browser_started = if ($authorizationHandoff) { [bool]$authorizationHandoff.no_browser_started } else { $true }
            no_submit = if ($authorizationHandoff) { [bool]$authorizationHandoff.no_submit } else { $true }
            bundle_path = if ($authorizationHandoff) { [string]$authorizationHandoff.bundle_path } else { "" }
            readiness_status = if ($authorizationHandoff) { [string]$authorizationHandoff.readiness_status } else { "" }
            json_path = if (Test-Path $AuthorizationHandoffJsonPath) { $AuthorizationHandoffJsonPath } else { "" }
        }
        live_preflight = [ordered]@{
            status = $preflightStatus
            no_submit = if ($preflight) { [bool]$preflight.no_submit } else { $true }
            preflight_only = if ($preflight) { [bool]$preflight.preflight_only } else { $true }
            preflight_action_statuses = if ($preflight) { $preflight.preflight_action_statuses } else { @{} }
            missing_preflight_action_types = if ($preflight) { @($preflight.missing_preflight_action_types) } else { Empty-JsonArray }
            evidence_file_details = if ($preflight) { $preflight.evidence_file_details } else { @{} }
            environment_diagnostics = if ($preflight) { $preflight.environment_diagnostics } else { @{} }
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
        repository_cleanliness = [ordered]@{
            status = if (Test-Path $RepositoryCleanlinessJsonPath) { [string](Read-JsonObject $RepositoryCleanlinessJsonPath).status } else { "skipped" }
            passed = if (Test-Path $RepositoryCleanlinessJsonPath) { [bool](Read-JsonObject $RepositoryCleanlinessJsonPath).passed } else { $false }
            forbidden_count = if (Test-Path $RepositoryCleanlinessJsonPath) { [int](Read-JsonObject $RepositoryCleanlinessJsonPath).forbidden_count } else { 0 }
            json_path = if (Test-Path $RepositoryCleanlinessJsonPath) { $RepositoryCleanlinessJsonPath } else { "" }
        }
        windows_package_preflight = [ordered]@{
            status = if ($windowsPackagePreflight) { [string]$windowsPackagePreflight.status } else { "skipped" }
            ready_for_windows_build = if ($windowsPackagePreflight) { [bool]$windowsPackagePreflight.ready_for_windows_build } else { $false }
            final_delivery_ready = if ($windowsPackagePreflight) { [bool]$windowsPackagePreflight.final_delivery_ready } else { $false }
            missing_final_artifacts = if ($windowsPackagePreflight) { @($windowsPackagePreflight.missing_final_artifacts) } else { Empty-JsonArray }
            build_contract = if ($windowsPackagePreflight) { $windowsPackagePreflight.build_contract } else { @{} }
            json_path = if (Test-Path $WindowsPackagePreflightJsonPath) { $WindowsPackagePreflightJsonPath } else { "" }
        }
        client_delivery = [ordered]@{
            status = if ($clientDelivery) { [string]$clientDelivery.status } else { "skipped" }
            readiness = if ($clientDelivery) { [string]$clientDelivery.readiness } else { "" }
            contract_ok = if ($clientDelivery) { [bool]$clientDelivery.contract_ok } else { $false }
            acceptance_ready = if ($clientDelivery) { [bool]$clientDelivery.acceptance_ready } else { $false }
            final_delivery_ready = if ($clientDelivery) { [bool]$clientDelivery.final_delivery_ready } else { $false }
            failed_checks = if ($clientDelivery) { @($clientDelivery.failed_checks) } else { Empty-JsonArray }
            blockers = if ($clientDelivery) { @($clientDelivery.blockers) } else { Empty-JsonArray }
            delivery_check_path = if ($clientDelivery) { [string]$clientDelivery.delivery_check_path } else { "" }
            checks = if ($clientDelivery) { @($clientDelivery.checks) } else { Empty-JsonArray }
            json_path = if (Test-Path $ClientDeliveryJsonPath) { $ClientDeliveryJsonPath } else { "" }
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

function Add-FinalGateToAcceptanceSummary {
    param(
        [string]$SummaryPath,
        [string]$FinalGateJsonPath
    )
    if (!(Test-Path $SummaryPath) -or !(Test-Path $FinalGateJsonPath)) {
        return
    }
    $summary = Read-JsonObject $SummaryPath
    $finalGate = Read-JsonObject $FinalGateJsonPath
    if (!$summary -or !$finalGate) {
        return
    }
    $finalGate | Add-Member -NotePropertyName "json_path" -NotePropertyValue $FinalGateJsonPath -Force
    $summary | Add-Member -NotePropertyName "final_acceptance_gate" -NotePropertyValue $finalGate -Force
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
$licenseRefreshStdout = Join-Path $root "license_refresh_stdout.json"
$licenseRefreshJson = Join-Path $root "license_refresh_payload.json"
$activationStatusStdout = Join-Path $root "activation_status_stdout.json"
$activationStatusJson = Join-Path $root "activation_status_payload.json"
$liveAcceptanceStatusStdout = Join-Path $root "live_acceptance_status_stdout.json"
$liveAcceptanceStatusJson = Join-Path $root "live_acceptance_status_payload.json"
$authorizationHandoffStdout = Join-Path $root "authorization_handoff_stdout.json"
$authorizationHandoffJson = Join-Path $root "authorization_handoff_payload.json"
$authorizationHandoffZip = Join-Path $root "latest_reachops_authorization_handoff.zip"
$authorizationHandoffReadinessJson = Join-Path $root "latest_live_acceptance_readiness.json"
$authorizationHandoffReadinessMd = Join-Path $root "latest_live_acceptance_readiness.md"
$liveValidationStdout = Join-Path $root "live_validation_manifest_stdout.json"
$liveValidationJson = Join-Path $root "live_validation_manifest.json"
$repositoryCleanlinessStdout = Join-Path $root "repository_cleanliness_stdout.json"
$repositoryCleanlinessJson = Join-Path $root "repository_cleanliness_payload.json"
$windowsPackagePreflightStdout = Join-Path $root "windows_package_preflight_stdout.json"
$windowsPackagePreflightJson = Join-Path $root "windows_package_preflight.json"
$clientDeliveryStdout = Join-Path $root "client_delivery_stdout.json"
$clientDeliveryJson = Join-Path $root "client_delivery.json"
$goalStatusStdout = Join-Path $root "goal_status_stdout.json"
$goalStatusJson = Join-Path $root "goal_status_report.json"
$packageCheckStdout = Join-Path $root "delivery_package_check_stdout.json"
$packageCheckJson = Join-Path $root "delivery_package_check.json"
$finalGateStdout = Join-Path $root "final_acceptance_gate_stdout.json"
$finalGateJson = Join-Path $root "final_acceptance_gate.json"
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
if ($ReuseExistingUiStartup) {
    $existingUiStatePath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath "reports\growth_ops_smoke\growth_ui_startup_state.json"))
    $existingUiState = Read-JsonObject $existingUiStatePath
    $existingUiPid = if ($existingUiState -and $existingUiState.pid) { [int]$existingUiState.pid } else { 0 }
    $existingUiProcess = if ($existingUiPid -gt 0) { Get-Process -Id $existingUiPid -ErrorAction SilentlyContinue } else { $null }
    if ($existingUiState -and $existingUiProcess) {
        Write-Step "Reusing existing ReachOps UI startup smoke"
        $uiStartupPayload = [ordered]@{
            status = "ok"
            launcher = if ($existingUiState.launcher) { [string]$existingUiState.launcher } else { "start_reachops_ui_windows.ps1" }
            state_path = $existingUiStatePath
            pid = $existingUiPid
            process_running = $true
            interactive_task = if ($existingUiState.interactive_task) { [bool]$existingUiState.interactive_task } else { $false }
            task_name = if ($existingUiState.task_name) { [string]$existingUiState.task_name } else { "" }
            stdout = "reused_existing_ui_startup_state"
        }
        $uiStartupPayloadJson = $uiStartupPayload | ConvertTo-Json -Depth 8 -Compress
        Write-Host $uiStartupPayloadJson
        Write-Utf8NoBom -Path $uiStartupStdout -Content $uiStartupPayloadJson
        Write-Utf8NoBom -Path $uiStartupJson -Content $uiStartupPayloadJson
    } else {
        Write-Step "Existing UI startup smoke unavailable; running ReachOps UI startup smoke"
        Invoke-PowerShellCapture -StepName "ReachOps UI startup smoke" -StdoutPath $uiStartupStdout -Arguments @("-File", $uiStartupSmokeScript, "-Root", (Get-Location).ProviderPath, "-KeepRunning")
        Convert-StdoutJson -StdoutPath $uiStartupStdout -OutputPath $uiStartupJson | Out-Null
    }
} elseif (Test-Path $uiStartupSmokeScript) {
    Write-Step "ReachOps UI startup smoke"
    Invoke-PowerShellCapture -StepName "ReachOps UI startup smoke" -StdoutPath $uiStartupStdout -Arguments @("-File", $uiStartupSmokeScript, "-Root", (Get-Location).ProviderPath, "-KeepRunning")
    Convert-StdoutJson -StdoutPath $uiStartupStdout -OutputPath $uiStartupJson | Out-Null
} else {
    Write-Step "Skipping UI startup smoke: script not found"
}

Write-Step "ReachOps license refresh preview without browser"
$licenseRefreshArgs = @("tools\reachops_license_refresh.py", "--preview", "--json")
if ($LicenseEndpoint) {
    $licenseRefreshArgs += @("--endpoint", $LicenseEndpoint)
}
Invoke-PythonCapture -StepName "ReachOps license refresh preview" -StdoutPath $licenseRefreshStdout -Arguments $licenseRefreshArgs
Convert-StdoutJson -StdoutPath $licenseRefreshStdout -OutputPath $licenseRefreshJson | Out-Null

Write-Step "ReachOps activation status check without browser"
$activationStatusArgs = @("tools\reachops_activation_status_check.py", "--json")
if ($ActivationStatusPath) {
    $activationStatusArgs += @("--activation-status-path", $ActivationStatusPath)
}
$activationStatusOutput = & python @activationStatusArgs 2>&1
$activationStatusOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $activationStatusStdout -Content ($activationStatusOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $activationStatusStdout -OutputPath $activationStatusJson | Out-Null

Write-Step "ReachOps live acceptance status without browser"
$liveAcceptanceStatusArgs = @("tools\reachops_live_acceptance_status.py", "--profile-group", $ProfileGroup, "--profile-limit", "3", "--profile-scan-timeout", "5", "--limit", ([string]$Limit), "--target", $Target, "--json")
if ($ResolvedInputFile) {
    $liveAcceptanceStatusArgs += @("--local-inputs-path", $ResolvedInputFile)
}
if ($AllowPressureSubmit) {
    $liveAcceptanceStatusArgs += @("--allow-pressure-submit", $AllowPressureSubmit)
}
if ($ProfileIds) {
    $liveAcceptanceStatusArgs += @("--profile-ids", $ProfileIds)
}
if ($CommentVideoUrl) {
    $liveAcceptanceStatusArgs += @("--comment-video-url", $CommentVideoUrl)
}
if ($FollowProfileUrl) {
    $liveAcceptanceStatusArgs += @("--target-profile-url", $FollowProfileUrl)
}
if ($DmProfileUrl) {
    $liveAcceptanceStatusArgs += @("--dm-profile-url", $DmProfileUrl)
}
if ($TargetUsername) {
    $liveAcceptanceStatusArgs += @("--target-username", $TargetUsername)
}
if ($ActivationStatusPath) {
    $liveAcceptanceStatusArgs += @("--activation-status-path", $ActivationStatusPath)
}
if ($ConfirmAuthorizedTargets) {
    $liveAcceptanceStatusArgs += @("--confirm-authorized-targets")
}
$liveAcceptanceStatusOutput = & python @liveAcceptanceStatusArgs 2>&1
$liveAcceptanceStatusOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $liveAcceptanceStatusStdout -Content ($liveAcceptanceStatusOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $liveAcceptanceStatusStdout -OutputPath $liveAcceptanceStatusJson | Out-Null
$liveAcceptanceStatusPayload = Read-JsonObject $liveAcceptanceStatusJson

Write-Step "ReachOps authorization handoff bundle without browser"
$authorizationHandoffArgs = @("tools\reachops_authorization_handoff_bundle.py", "--profile-group", $ProfileGroup, "--profile-limit", "3", "--profile-scan-timeout", "5", "--limit", ([string]$Limit), "--target", $Target, "--output-path", $authorizationHandoffZip, "--json")
if ($ResolvedInputFile) {
    $authorizationHandoffArgs += @("--local-inputs-path", $ResolvedInputFile)
}
if ($AllowPressureSubmit) {
    $authorizationHandoffArgs += @("--allow-pressure-submit", $AllowPressureSubmit)
}
if ($ProfileIds) {
    $authorizationHandoffArgs += @("--profile-ids", $ProfileIds)
}
if ($CommentVideoUrl) {
    $authorizationHandoffArgs += @("--comment-video-url", $CommentVideoUrl)
}
if ($FollowProfileUrl) {
    $authorizationHandoffArgs += @("--target-profile-url", $FollowProfileUrl)
}
if ($DmProfileUrl) {
    $authorizationHandoffArgs += @("--dm-profile-url", $DmProfileUrl)
}
if ($TargetUsername) {
    $authorizationHandoffArgs += @("--target-username", $TargetUsername)
}
if ($ActivationStatusPath) {
    $authorizationHandoffArgs += @("--activation-status-path", $ActivationStatusPath)
}
if ($ConfirmAuthorizedTargets) {
    $authorizationHandoffArgs += @("--confirm-authorized-targets")
}
$authorizationHandoffOutput = & python @authorizationHandoffArgs 2>&1
$authorizationHandoffOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $authorizationHandoffStdout -Content ($authorizationHandoffOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $authorizationHandoffStdout -OutputPath $authorizationHandoffJson | Out-Null

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

Write-Step "ReachOps repository cleanliness check"
Invoke-PythonCapture -StepName "ReachOps repository cleanliness check" -StdoutPath $repositoryCleanlinessStdout -Arguments @("tools\reachops_repository_cleanliness_check.py", "--json")
Convert-StdoutJson -StdoutPath $repositoryCleanlinessStdout -OutputPath $repositoryCleanlinessJson | Out-Null

Write-Step "ReachOps Windows package preflight"
Invoke-PythonCapture -StepName "ReachOps Windows package preflight" -StdoutPath $windowsPackagePreflightStdout -Arguments @("tools\reachops_windows_package_preflight.py", "--json")
Convert-StdoutJson -StdoutPath $windowsPackagePreflightStdout -OutputPath $windowsPackagePreflightJson | Out-Null

Write-Step "ReachOps client delivery gate"
$clientDeliveryOutput = & python @("tools\reachops_client_delivery_check.py", "--output", $clientDeliveryJson, "--json") 2>&1
$clientDeliveryOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $clientDeliveryStdout -Content ($clientDeliveryOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $clientDeliveryStdout -OutputPath $clientDeliveryJson | Out-Null

Write-Step "ReachOps live submit readiness check without browser"
$readinessArgs = @("tools\reachops_live_readiness.py", "--limit", ([string]$Limit), "--json")
if ($ProfileIds) {
    $readinessArgs += @("--profile-ids", $ProfileIds)
}
if ($ProfileGroup) {
    $readinessArgs += @("--group-name", $ProfileGroup)
}
if ($CommentVideoUrl) {
    $readinessArgs += @("--video-url", $CommentVideoUrl)
}
if ($FollowProfileUrl) {
    $readinessArgs += @("--follow-profile-url", $FollowProfileUrl, "--dm-profile-url", $(if ($DmProfileUrl) { $DmProfileUrl } else { $FollowProfileUrl }))
}
if ($TargetUsername) {
    $readinessArgs += @("--target-username", $TargetUsername)
}
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
if ($readinessPayload -and (-not [bool]$readinessPayload.ready)) {
    Write-Step "Live readiness is blocked; still writing no-submit preflight input report"
}

Write-Step "ReachOps live preflight without submit"
$preflightArgs = @("tools\reachops_live_preflight.py", "--base-dir", (Join-Path $root "live_preflight"), "--workers", "2", "--per-profile-limit", "3", "--switch-attempts", "2", "--page-timeout", "45", "--element-timeout", "25", "--json")
if ($ProfileIds) {
    $preflightArgs += @("--profile-ids", $ProfileIds)
}
if ($ProfileGroup) {
    $preflightArgs += @("--group-name", $ProfileGroup)
}
if ($CommentVideoUrl) {
    $preflightArgs += @("--video-url", $CommentVideoUrl)
}
if ($FollowProfileUrl) {
    $preflightArgs += @("--profile-url", $FollowProfileUrl)
}
if ($DmProfileUrl) {
    $preflightArgs += @("--dm-profile-url", $DmProfileUrl)
}
if ($TargetUsername) {
    $preflightArgs += @("--target-username", $TargetUsername)
}
$preflightOutput = & python @preflightArgs 2>&1
$preflightOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $preflightStdout -Content ($preflightOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $preflightStdout -OutputPath $preflightJson | Out-Null

if ($RunLiveSubmit) {
    if (-not $ConfirmAuthorizedTargets) {
        throw "RunLiveSubmit requires -ConfirmAuthorizedTargets."
    }
    if ($ResolvedInputFile -and (-not ($liveAcceptanceStatusPayload -and $liveAcceptanceStatusPayload.local_inputs -and [bool]$liveAcceptanceStatusPayload.local_inputs.usable))) {
        $fieldStates = ""
        if ($liveAcceptanceStatusPayload -and $liveAcceptanceStatusPayload.local_inputs -and $liveAcceptanceStatusPayload.local_inputs.field_status) {
            $fieldStates = ($liveAcceptanceStatusPayload.local_inputs.field_status.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value.state)" }) -join ", "
        }
        throw "RunLiveSubmit requires InputFile local_inputs.usable=true. Replace placeholders and confirm authorized targets first. Field states: $fieldStates"
    }
    if ($liveAcceptanceStatusPayload -and (-not [bool]$liveAcceptanceStatusPayload.ready_for_live_submit)) {
        throw "RunLiveSubmit requires live acceptance status ready_for_live_submit=true."
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

Write-AcceptanceSummary -OutputPath $acceptanceSummaryJson -RootDir $root -AuditJsonPath $auditJson -OperatorPressureJsonPath $operatorPressureJson -InstallerSmokeJsonPath $installerSmokeJson -UiStartupJsonPath $uiStartupJson -LicenseRefreshJsonPath $licenseRefreshJson -ActivationStatusJsonPath $activationStatusJson -LiveAcceptanceStatusJsonPath $liveAcceptanceStatusJson -AuthorizationHandoffJsonPath $authorizationHandoffJson -LiveValidationJsonPath $liveValidationJson -RepositoryCleanlinessJsonPath $repositoryCleanlinessJson -WindowsPackagePreflightJsonPath $windowsPackagePreflightJson -ClientDeliveryJsonPath $clientDeliveryJson -ReadinessJsonPath $readinessJson -PreflightJsonPath $preflightJson -LiveSubmitJsonPath $liveSubmitJson -InstallerOptional ([bool]$AllowMissingInstaller)

Write-Step "ReachOps goal status report"
Invoke-PythonCapture -StepName "ReachOps goal status report" -StdoutPath $goalStatusStdout -Arguments @("tools\reachops_goal_status_report.py", "--audit-json", $auditJson, "--acceptance-summary", $acceptanceSummaryJson, "--json")
Convert-StdoutJson -StdoutPath $goalStatusStdout -OutputPath $goalStatusJson | Out-Null
Add-GoalStatusToAcceptanceSummary -SummaryPath $acceptanceSummaryJson -GoalStatusJsonPath $goalStatusJson

Write-Step "ReachOps delivery package check"
$packageCheckArgs = @("tools\reachops_delivery_package_check.py", "--acceptance-summary", $acceptanceSummaryJson, "--json")
$packageCheckBootstrapArgs = @("tools\reachops_delivery_package_check.py", "--acceptance-summary", $acceptanceSummaryJson, "--json", "--allow-missing-final-gate")
$packageCheckConvergenceArgs = @("tools\reachops_delivery_package_check.py", "--acceptance-summary", $acceptanceSummaryJson, "--json", "--allow-final-gate-convergence")
$currentSummary = Read-JsonObject $acceptanceSummaryJson
if (-not ($currentSummary -and [string]$currentSummary.status -eq "passed")) {
    $packageCheckArgs += @("--allow-external-pending")
    $packageCheckBootstrapArgs += @("--allow-external-pending")
    $packageCheckConvergenceArgs += @("--allow-external-pending")
}
$packageCheckOutput = & python @packageCheckBootstrapArgs 2>&1
$packageCheckOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $packageCheckStdout -Content ($packageCheckOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $packageCheckStdout -OutputPath $packageCheckJson | Out-Null
$packageCheckPayload = Read-JsonObject $packageCheckJson
if ($currentSummary -and [string]$currentSummary.status -eq "passed" -and (-not ($packageCheckPayload -and [bool]$packageCheckPayload.passed))) {
    throw "ReachOps delivery package check failed for final passed acceptance. See $packageCheckJson"
}

Write-Step "ReachOps strict final acceptance gate"
$finalGateArgs = @(
    "tools\reachops_final_acceptance_gate.py",
    "--audit-json", $auditJson,
    "--pressure-json", $operatorPressureJson,
    "--goal-status-json", $goalStatusJson,
    "--package-check-json", $packageCheckJson,
    "--acceptance-summary", $acceptanceSummaryJson,
    "--json"
)
$finalGateOutput = & python @finalGateArgs 2>&1
$finalGateOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $finalGateStdout -Content ($finalGateOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $finalGateStdout -OutputPath $finalGateJson | Out-Null
$finalGatePayload = Read-JsonObject $finalGateJson
Add-FinalGateToAcceptanceSummary -SummaryPath $acceptanceSummaryJson -FinalGateJsonPath $finalGateJson

Write-Step "ReachOps delivery package convergence evidence check"
$packageCheckOutput = & python @packageCheckConvergenceArgs 2>&1
$packageCheckOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $packageCheckStdout -Content ($packageCheckOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $packageCheckStdout -OutputPath $packageCheckJson | Out-Null
$packageCheckPayload = Read-JsonObject $packageCheckJson
if ($currentSummary -and [string]$currentSummary.status -eq "passed" -and (-not ($packageCheckPayload -and [bool]$packageCheckPayload.passed))) {
    throw "ReachOps delivery package convergence evidence check failed for final passed acceptance. See $packageCheckJson"
}

Write-Step "ReachOps strict final acceptance gate final evidence check"
$finalGateOutput = & python @finalGateArgs 2>&1
$finalGateOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $finalGateStdout -Content ($finalGateOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $finalGateStdout -OutputPath $finalGateJson | Out-Null
$finalGatePayload = Read-JsonObject $finalGateJson
Add-FinalGateToAcceptanceSummary -SummaryPath $acceptanceSummaryJson -FinalGateJsonPath $finalGateJson
if ($currentSummary -and [string]$currentSummary.status -eq "passed" -and (-not ($finalGatePayload -and [bool]$finalGatePayload.final_delivery_ready))) {
    throw "ReachOps final acceptance gate failed for final passed acceptance. See $finalGateJson"
}

Write-Step "ReachOps delivery package strict final evidence check"
$packageCheckOutput = & python @packageCheckArgs 2>&1
$packageCheckOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $packageCheckStdout -Content ($packageCheckOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $packageCheckStdout -OutputPath $packageCheckJson | Out-Null
$packageCheckPayload = Read-JsonObject $packageCheckJson
if ($currentSummary -and [string]$currentSummary.status -eq "passed" -and (-not ($packageCheckPayload -and [bool]$packageCheckPayload.passed))) {
    throw "ReachOps delivery package strict final evidence check failed for final passed acceptance. See $packageCheckJson"
}

Write-Step "ReachOps strict final acceptance gate after package convergence"
$finalGateOutput = & python @finalGateArgs 2>&1
$finalGateOutput | ForEach-Object { Write-Host $_ }
Write-Utf8NoBom -Path $finalGateStdout -Content ($finalGateOutput -join [Environment]::NewLine)
Convert-StdoutJson -StdoutPath $finalGateStdout -OutputPath $finalGateJson | Out-Null
$finalGatePayload = Read-JsonObject $finalGateJson
Add-FinalGateToAcceptanceSummary -SummaryPath $acceptanceSummaryJson -FinalGateJsonPath $finalGateJson
if ($currentSummary -and [string]$currentSummary.status -eq "passed" -and (-not ($finalGatePayload -and [bool]$finalGatePayload.final_delivery_ready))) {
    throw "ReachOps strict final acceptance gate after package convergence failed for final passed acceptance. See $finalGateJson"
}

Write-Step "ReachOps acceptance artifacts written under $root"
Write-Host "REACHOPS_ACCEPTANCE_DIR=$root"
Write-Host "DELIVERY_AUDIT_JSON=$auditJson"
Write-Host "OPERATOR_PRESSURE_JSON=$operatorPressureJson"
Write-Host "ACTIVATION_STATUS_JSON=$activationStatusJson"
Write-Host "LIVE_ACCEPTANCE_STATUS_JSON=$liveAcceptanceStatusJson"
Write-Host "LIVE_VALIDATION_MANIFEST_JSON=$liveValidationJson"
Write-Host "REPOSITORY_CLEANLINESS_JSON=$repositoryCleanlinessJson"
Write-Host "WINDOWS_PACKAGE_PREFLIGHT_JSON=$windowsPackagePreflightJson"
Write-Host "CLIENT_DELIVERY_JSON=$clientDeliveryJson"
Write-Host "GOAL_STATUS_JSON=$goalStatusJson"
Write-Host "PACKAGE_CHECK_JSON=$packageCheckJson"
Write-Host "FINAL_ACCEPTANCE_GATE_JSON=$finalGateJson"
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
