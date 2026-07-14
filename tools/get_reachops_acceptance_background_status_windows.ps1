param(
    [string]$RunDir = "",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$FinalVerificationCommands = @(
    "python tools\reachops_client_delivery_check.py --json",
    "python tools\reachops_goal_delivery_runner.py --json",
    "python tools\reachops_delivery_package_check.py --json",
    "python tools\reachops_issue_closure_audit.py --json",
    "python tools\reachops_final_acceptance_gate.py --json"
)

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

function Read-JsonObject {
    param([string]$Path)
    if (!(Test-Path $Path)) {
        return $null
    }
    return Get-Content -Path $Path -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
}

function Convert-StdoutJson {
    param([string]$Raw)
    if ([string]::IsNullOrWhiteSpace($Raw)) {
        return $null
    }
    $idx = $Raw.LastIndexOf("{")
    while ($idx -ge 0) {
        $candidate = $Raw.Substring($idx).Trim()
        try {
            return $candidate | ConvertFrom-Json -ErrorAction Stop
        } catch {
            if ($idx -eq 0) {
                break
            }
            $idx = $Raw.LastIndexOf("{", $idx - 1)
        }
    }
    return $null
}

if (-not $RunDir) {
    $latest = Get-ChildItem "reports\reachops_acceptance_background" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($latest) {
        $RunDir = $latest.FullName
    }
}

if (-not $RunDir) {
    $result = [ordered]@{
        status = "missing"
        error = "no background acceptance run found"
    }
    if ($Json) {
        Write-Host ($result | ConvertTo-Json -Depth 8 -Compress)
    } else {
        Write-Host "ReachOps background acceptance status: missing"
    }
    exit 2
}

$recordPath = Join-Path $RunDir "acceptance_background_run.json"
$record = Read-JsonObject $recordPath
$processId = if ($record) { [int]$record.pid } else { 0 }
$taskName = if ($record -and $record.task_name) { [string]$record.task_name } else { "" }
$taskState = ""
$taskLastResult = $null
$running = $false
if ($processId -gt 0) {
    $running = [bool](Get-Process -Id $processId -ErrorAction SilentlyContinue)
}
if ($taskName) {
    $taskInfo = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($taskInfo) {
        $taskState = [string]$taskInfo.State
        $taskDetails = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        if ($taskDetails) {
            $taskLastResult = $taskDetails.LastTaskResult
        }
        if ($taskState -eq "Running") {
            $running = $true
        }
    }
}

$stdoutPath = if ($record -and $record.stdout_path) { [string]$record.stdout_path } else { Join-Path $RunDir "acceptance_stdout.log" }
$stderrPath = if ($record -and $record.stderr_path) { [string]$record.stderr_path } else { Join-Path $RunDir "acceptance_stderr.log" }
$stdoutTail = ""
$stderrTail = ""
if (Test-Path $stdoutPath) {
    $stdoutTail = ((Get-Content -Path $stdoutPath -Tail 40 -Encoding UTF8) -join [Environment]::NewLine)
}
if (Test-Path $stderrPath) {
    $stderrTail = ((Get-Content -Path $stderrPath -Tail 40 -Encoding UTF8) -join [Environment]::NewLine)
}

$acceptanceSummaryPath = ""
$finalAcceptanceGatePath = ""
$issueClosurePath = ""
$deliveryPackageCheckPath = ""
$windowsPackagePreflightPath = ""
if (Test-Path $stdoutPath) {
    $summaryLine = Get-Content -Path $stdoutPath -Encoding UTF8 |
        Where-Object { $_ -like "ACCEPTANCE_SUMMARY_JSON=*" } |
        Select-Object -Last 1
    if ($summaryLine) {
        $acceptanceSummaryPath = [string]$summaryLine.Substring("ACCEPTANCE_SUMMARY_JSON=".Length)
    }
    $finalGateLine = Get-Content -Path $stdoutPath -Encoding UTF8 |
        Where-Object { $_ -like "FINAL_ACCEPTANCE_GATE_JSON=*" } |
        Select-Object -Last 1
    if ($finalGateLine) {
        $finalAcceptanceGatePath = [string]$finalGateLine.Substring("FINAL_ACCEPTANCE_GATE_JSON=".Length)
    }
    $issueClosureLine = Get-Content -Path $stdoutPath -Encoding UTF8 |
        Where-Object { $_ -like "ISSUE_CLOSURE_JSON=*" } |
        Select-Object -Last 1
    if ($issueClosureLine) {
        $issueClosurePath = [string]$issueClosureLine.Substring("ISSUE_CLOSURE_JSON=".Length)
    }
    $windowsPreflightLine = Get-Content -Path $stdoutPath -Encoding UTF8 |
        Where-Object { $_ -like "WINDOWS_PACKAGE_PREFLIGHT_JSON=*" } |
        Select-Object -Last 1
    if ($windowsPreflightLine) {
        $windowsPackagePreflightPath = [string]$windowsPreflightLine.Substring("WINDOWS_PACKAGE_PREFLIGHT_JSON=".Length)
    }
}
if ($acceptanceSummaryPath) {
    $deliveryPackageCheckPath = Join-Path (Split-Path -Parent $acceptanceSummaryPath) "delivery_package_check.json"
    if (-not $windowsPackagePreflightPath) {
        $windowsPackagePreflightPath = Join-Path (Split-Path -Parent $acceptanceSummaryPath) "windows_package_preflight.json"
    }
    if (-not $issueClosurePath) {
        $issueClosurePath = Join-Path (Split-Path -Parent $acceptanceSummaryPath) "issue_closure_payload.json"
    }
}

$acceptanceSummary = $null
$acceptanceVerification = $null
$finalAcceptanceGate = $null
$issueClosure = $null
$deliveryPackageCheck = $null
$windowsPackagePreflight = $null
if ($acceptanceSummaryPath -and (Test-Path $acceptanceSummaryPath)) {
    $acceptanceSummary = Read-JsonObject $acceptanceSummaryPath
    $verifyOutput = & python tools\verify_reachops_acceptance_summary.py $acceptanceSummaryPath --allow-external-pending --json 2>&1
    $acceptanceVerification = Convert-StdoutJson (($verifyOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
}
if ($finalAcceptanceGatePath -and (Test-Path $finalAcceptanceGatePath)) {
    $finalAcceptanceGate = Read-JsonObject $finalAcceptanceGatePath
}
if ($issueClosurePath -and (Test-Path $issueClosurePath)) {
    $issueClosure = Read-JsonObject $issueClosurePath
}
if ($deliveryPackageCheckPath -and (Test-Path $deliveryPackageCheckPath)) {
    $deliveryPackageCheck = Read-JsonObject $deliveryPackageCheckPath
}
if ($windowsPackagePreflightPath -and (Test-Path $windowsPackagePreflightPath)) {
    $windowsPackagePreflight = Read-JsonObject $windowsPackagePreflightPath
}

$finalGateFailedChecks = @()
if ($finalAcceptanceGate -and $finalAcceptanceGate.failed_checks) {
    $finalGateFailedChecks = @($finalAcceptanceGate.failed_checks)
}
$acceptanceFinalPassed = [bool](
    $acceptanceSummary `
    -and [string]$acceptanceSummary.status -eq "passed" `
    -and $acceptanceVerification `
    -and [bool]$acceptanceVerification.passed
)
$finalGateReady = [bool](
    $finalAcceptanceGate `
    -and [string]$finalAcceptanceGate.status -eq "passed" `
    -and [bool]$finalAcceptanceGate.final_delivery_ready `
    -and $finalGateFailedChecks.Count -eq 0
)
$deliveryPackageReady = [bool](
    $deliveryPackageCheck `
    -and [string]$deliveryPackageCheck.status -eq "passed" `
    -and [bool]$deliveryPackageCheck.passed `
    -and [bool]$deliveryPackageCheck.final_delivery_ready `
    -and (-not [bool]$deliveryPackageCheck.bootstrap_only) `
    -and $deliveryPackageCheck.final_gate_report `
    -and [string]$deliveryPackageCheck.final_gate_report.status -eq "passed" `
    -and [bool]$deliveryPackageCheck.final_gate_report.final_delivery_ready `
    -and (-not $deliveryPackageCheck.final_gate_report.failed_checks -or @($deliveryPackageCheck.final_gate_report.failed_checks).Count -eq 0) `
    -and (-not $deliveryPackageCheck.final_gate_report.missing_required_checks -or @($deliveryPackageCheck.final_gate_report.missing_required_checks).Count -eq 0) `
    -and (-not $deliveryPackageCheck.final_gate_report.failed_required_checks -or @($deliveryPackageCheck.final_gate_report.failed_required_checks).Count -eq 0) `
    -and $deliveryPackageCheck.final_gate_report.checks_by_name `
    -and $deliveryPackageCheck.report_files `
    -and $deliveryPackageCheck.report_files.windows_package_preflight `
    -and [bool]$deliveryPackageCheck.report_files.windows_package_preflight.exists `
    -and [int]$deliveryPackageCheck.report_files.windows_package_preflight.size -gt 0 `
    -and $deliveryPackageCheck.report_files.issue_closure `
    -and [bool]$deliveryPackageCheck.report_files.issue_closure.exists `
    -and [int]$deliveryPackageCheck.report_files.issue_closure.size -gt 0 `
    -and $deliveryPackageCheck.report_files.client_delivery `
    -and [bool]$deliveryPackageCheck.report_files.client_delivery.exists `
    -and [int]$deliveryPackageCheck.report_files.client_delivery.size -gt 0
)
$issueClosureSummary = if ($issueClosure -and $issueClosure.summary) { $issueClosure.summary } else { $null }
$issueClosureGithubIssues = if ($issueClosure -and $issueClosure.github_issues) { $issueClosure.github_issues } else { $null }
$issueClosureReady = [bool](
    $issueClosure `
    -and [bool]$issueClosure.passed `
    -and $issueClosureSummary `
    -and [int]$issueClosureSummary.issues_total -eq 7 `
    -and [int]$issueClosureSummary.acceptance_criteria_total -eq 53 `
    -and [int]$issueClosureSummary.acceptance_criteria_unclassified -eq 0 `
    -and [int]$issueClosureSummary.acceptance_criteria_external_pending -eq 0 `
    -and [int]$issueClosureSummary.external_pending_count -eq 0 `
    -and (-not $issueClosure.external_acceptance_pending -or @($issueClosure.external_acceptance_pending).Count -eq 0) `
    -and $issueClosureGithubIssues `
    -and (-not [bool]$issueClosureGithubIssues.closure_requires_external_validation)
)
$finalDeliveryReady = [bool]($acceptanceFinalPassed -and $deliveryPackageReady -and $finalGateReady -and $issueClosureReady)
$finalDeliveryBlockers = @()
if (-not $acceptanceSummary) {
    $finalDeliveryBlockers += "acceptance_summary_missing"
} elseif ([string]$acceptanceSummary.status -ne "passed") {
    $finalDeliveryBlockers += "acceptance_summary_not_passed"
}
if (-not $acceptanceVerification) {
    $finalDeliveryBlockers += "acceptance_verification_missing"
} elseif (-not [bool]$acceptanceVerification.passed) {
    $finalDeliveryBlockers += "acceptance_verification_not_passed"
}
if (-not $finalAcceptanceGate) {
    $finalDeliveryBlockers += "final_acceptance_gate_missing"
} elseif (-not $finalGateReady) {
    $finalDeliveryBlockers += "final_acceptance_gate_not_ready"
}
if (-not $deliveryPackageCheck) {
    $finalDeliveryBlockers += "delivery_package_check_missing"
} elseif (-not $deliveryPackageReady) {
    $finalDeliveryBlockers += "delivery_package_check_not_final_ready"
}
if (-not $windowsPackagePreflight) {
    $finalDeliveryBlockers += "windows_package_preflight_missing"
} elseif ([string]$windowsPackagePreflight.status -ne "ready_for_windows_build" -or -not [bool]$windowsPackagePreflight.ready_for_windows_build) {
    $finalDeliveryBlockers += "windows_package_preflight_not_ready"
}
if (-not $issueClosure) {
    $finalDeliveryBlockers += "issue_closure_missing"
} elseif (-not $issueClosureReady) {
    $finalDeliveryBlockers += "issue_closure_not_closed"
}
if (-not ($deliveryPackageCheck -and $deliveryPackageCheck.report_files -and $deliveryPackageCheck.report_files.client_delivery -and [bool]$deliveryPackageCheck.report_files.client_delivery.exists -and [int]$deliveryPackageCheck.report_files.client_delivery.size -gt 0)) {
    $finalDeliveryBlockers += "client_delivery_report_missing"
}
if (-not ($deliveryPackageCheck -and $deliveryPackageCheck.report_files -and $deliveryPackageCheck.report_files.issue_closure -and [bool]$deliveryPackageCheck.report_files.issue_closure.exists -and [int]$deliveryPackageCheck.report_files.issue_closure.size -gt 0)) {
    $finalDeliveryBlockers += "issue_closure_report_missing"
}

$status = "running"
if (-not $running) {
    if ($acceptanceSummary) {
        $status = [string]$acceptanceSummary.status
    } elseif ($null -ne $taskLastResult -and [int]$taskLastResult -ne 0) {
        $status = "failed"
    } elseif ($stderrTail) {
        $status = "failed"
    } else {
        $status = "exited_without_summary"
    }
}

$result = [ordered]@{
    status = $status
    running = $running
    pid = $processId
    task_name = $taskName
    task_state = $taskState
    task_last_result = $taskLastResult
    run_dir = $RunDir
    record_path = $recordPath
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    acceptance_summary_path = $acceptanceSummaryPath
    acceptance_summary_exists = [bool]($acceptanceSummaryPath -and (Test-Path $acceptanceSummaryPath))
    acceptance_verification = $acceptanceVerification
    delivery_package_check_path = $deliveryPackageCheckPath
    delivery_package_check_exists = [bool]($deliveryPackageCheckPath -and (Test-Path $deliveryPackageCheckPath))
    delivery_package_check = $deliveryPackageCheck
    windows_package_preflight_path = $windowsPackagePreflightPath
    windows_package_preflight_exists = [bool]($windowsPackagePreflightPath -and (Test-Path $windowsPackagePreflightPath))
    windows_package_preflight = $windowsPackagePreflight
    issue_closure_path = $issueClosurePath
    issue_closure_exists = [bool]($issueClosurePath -and (Test-Path $issueClosurePath))
    issue_closure = $issueClosure
    issue_closure_ready = $issueClosureReady
    final_acceptance_gate_path = $finalAcceptanceGatePath
    final_acceptance_gate_exists = [bool]($finalAcceptanceGatePath -and (Test-Path $finalAcceptanceGatePath))
    final_acceptance_gate = $finalAcceptanceGate
    final_delivery_ready = $finalDeliveryReady
    final_delivery_blockers = $finalDeliveryBlockers
    verification_commands = $FinalVerificationCommands
    stdout_tail = $stdoutTail
    stderr_tail = $stderrTail
}

if ($Json) {
    Write-Host ($result | ConvertTo-Json -Depth 12 -Compress)
} else {
    Write-Host "ReachOps background acceptance status: $status"
    Write-Host "RUN_DIR=$RunDir"
    Write-Host "PID=$processId"
    if ($taskName) {
        Write-Host "TASK_NAME=$taskName"
        Write-Host "TASK_STATE=$taskState"
        Write-Host "TASK_LAST_RESULT=$taskLastResult"
    }
    Write-Host "RUNNING=$running"
    if ($acceptanceSummaryPath) {
        Write-Host "ACCEPTANCE_SUMMARY_JSON=$acceptanceSummaryPath"
    }
    if ($finalAcceptanceGatePath) {
        Write-Host "FINAL_ACCEPTANCE_GATE_JSON=$finalAcceptanceGatePath"
    }
    if ($issueClosurePath) {
        Write-Host "ISSUE_CLOSURE_JSON=$issueClosurePath"
    }
    if ($windowsPackagePreflightPath) {
        Write-Host "WINDOWS_PACKAGE_PREFLIGHT_JSON=$windowsPackagePreflightPath"
    }
    Write-Host "FINAL_DELIVERY_READY=$finalDeliveryReady"
    if ($finalDeliveryBlockers.Count -gt 0) {
        Write-Host ("FINAL_DELIVERY_BLOCKERS=" + ($finalDeliveryBlockers -join ","))
    }
    Write-Host ("VERIFICATION_COMMANDS=" + ($FinalVerificationCommands -join " ; "))
}
